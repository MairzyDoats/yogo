import torch


import torchvision.ops as ops

from typing import (
    Tuple,
    Optional,
    Literal,
    get_args,
)


BoxFormat = Literal["xyxy", "cxcywh"]


def format_preds(
    pred: torch.Tensor,
    obj_thresh: float = 0.5,
    iou_thresh: float = 0.5,
    area_thresh: Optional[float] = None,
    box_format: BoxFormat = "cxcywh",
) -> torch.Tensor:
    """
    formats pred, prediction tensor straight from YOGO, into [N,pred_shape], after applying NMS,
    and, thresholding objectness, and filtering thin boxes. box_format specifies the returned box format.

    area_thresh is the threshold for filtering out boxes that are too small (in units of pct of image).
    An OK lower bound is 1e-6

    For all thresholds, set to 0 to disable.
    """
    if len(pred.shape) != 3:
        raise ValueError(
            "argument to format_pred should be unbatched result - "
            f"shape should be (pred_shape, Sy, Sx), got {pred.shape}"
        )
    elif box_format not in get_args(BoxFormat):
        raise ValueError(
            f"invalid box format {box_format}; valid box formats are {get_args(BoxFormat)}"
        )

    pred_shape, Sy, Sx = pred.shape

    reformatted_preds = pred.view(pred_shape, Sx * Sy).T

    # Filter for objectness first
    objectness_mask = (reformatted_preds[:, 4] > obj_thresh).bool()
    preds = reformatted_preds[objectness_mask]

    if area_thresh is not None:
        # filter on area (discard small bboxes)
        areas = (Sx / Sy) * preds[:, 2] * preds[:, 3]
        areas_mask = area_thresh <= areas

        preds = preds[areas_mask]

    # if we have to convert box format to xyxy, do it to the tensor
    # and give nms a view of the original. Otherwise, just give nms
    # the a converted clone of the boxes.
    if box_format == "xyxy":
        preds[:, :4] = ops.box_convert(preds[:, :4], "cxcywh", "xyxy")
        nms_boxes = preds[:, :4]
    elif box_format == "cxcywh":
        nms_boxes = ops.box_convert(preds[:, :4], "cxcywh", "xyxy")

    # Non-maximal supression to remove duplicate boxes
    if iou_thresh > 0:
        keep_idxs = ops.nms(
            nms_boxes,
            preds[:, 4],
            iou_threshold=iou_thresh,
        )
    else:
        keep_idxs = torch.arange(len(preds))

    return preds[keep_idxs]


def format_preds_and_labels(
    pred: torch.Tensor,
    label: torch.Tensor,
    use_IoU: bool = True,
    objectness_thresh: float = 0.5,
) -> Tuple[torch.Tensor, torch.Tensor]:
    """A very important utility function for filtering predictions on labels

    Often, we need to calculate conditional probabilites - e.g. #(correct predictions | objectness > thresh)
    We want to select our predicted bbs and class predictions on IOU, and sometimes on ojbectness, e.t.c

    preds and labels are the batch label and prediction tensors, hot n' fresh from the model and dataloader!
    use_IoU is whether to use IoU instead of naive cell matching. More accurate, but slower.
    objectness_thresh is the "objectness" threshold, YOGO's confidence that there is a prediction in the given cell. Can
        only be used with use_IoU == True

    returns
        tuple(
            tensor of predictions shape=[N, x y x y objectness *classes],
            tensor of labels shape=[N, mask x y x y class]
        )
    """
    pred.squeeze_()
    label.squeeze_()

    if len(pred.shape) != 3:
        raise ValueError(
            "argument to format_pred should be unbatched result - "
            f"shape should be (pred_shape, Sy, Sx), got {pred.shape}"
        )

    if not (0 <= objectness_thresh < 1):
        raise ValueError(
            f"must have 0 <= objectness_thresh < 1; got objectness_thresh={objectness_thresh}"
        )

    (
        pred_shape,
        Sy,
        Sx,
    ) = pred.shape  # pred_shape is xc yc w h objectness *classes
    (
        label_shape,
        Sy,
        Sx,
    ) = label.shape  # label_shape is mask x y x y class

    reformatted_preds = pred.view(pred_shape, Sx * Sy).T
    reformatted_labels = label.view(label_shape, Sx * Sy).T

    # reformatted_labels[:, 0] = 1 if there is a label for that cell, else 0
    labels_mask = reformatted_labels[:, 0].bool()
    objectness_mask = (reformatted_preds[:, 4] > objectness_thresh).bool()

    img_masked_labels = reformatted_labels[labels_mask]

    if use_IoU and objectness_mask.sum() >= len(img_masked_labels):
        # filter on objectness
        preds_with_objects = reformatted_preds[objectness_mask]

        preds_with_objects[:, 0:4] = ops.box_convert(
            preds_with_objects[:, 0:4], "cxcywh", "xyxy"
        )

        # choose predictions from argmaxed IoU along label dim to get best prediction per label
        prediction_matrix = ops.box_iou(
            img_masked_labels[:, 1:5], preds_with_objects[:, 0:4]
        )
        n, m = prediction_matrix.shape
        if m > 0:
            prediction_indices = prediction_matrix.argmax(dim=1)
        else:
            # no predictions!
            prediction_indices = []
        final_preds = preds_with_objects[prediction_indices]
    else:
        # filter on label tensor idx
        final_preds = reformatted_preds[reformatted_labels[:, 0].bool()]
        final_preds[:, 0:4] = ops.box_convert(final_preds[:, 0:4], "cxcywh", "xyxy")

    return final_preds, img_masked_labels