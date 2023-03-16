#! /usr/bin/env python3

import torch

import torchvision.ops as ops
import torchvision.transforms as T

from PIL import Image, ImageDraw
from typing import Optional, Union, List

from torchmetrics import ConfusionMatrix
from torchmetrics.detection.mean_ap import MeanAveragePrecision
from torchmetrics.classification import MulticlassPrecisionRecallCurve

from typing import Optional, Tuple, List, Dict


class Metrics:
    def __init__(
        self,
        num_classes: int,
        device: str = "cpu",
        class_names: Optional[List[str]] = None,
    ):
        self.mAP = MeanAveragePrecision(box_format="cxcywh")
        self.confusion = ConfusionMatrix(task="multiclass", num_classes=num_classes)
        self.confusion.to(device)

        self.precision_recall = MulticlassPrecisionRecallCurve(num_classes=num_classes)

        self.num_classes = num_classes
        self.class_names = (
            list(range(num_classes)) if class_names is None else class_names
        )
        assert self.num_classes == len(self.class_names)

    def update(self, preds, labels):
        bs, pred_shape, Sy, Sx = preds.shape
        bs, label_shape, Sy, Sx = labels.shape

        confusion_preds, confusion_labels = self.format_for_confusion(
            batch_preds=preds, batch_labels=labels
        )
        self.confusion.update(confusion_preds, confusion_labels)

        mAP_preds, mAP_labels = self.format_for_mAP(preds, labels)
        self.mAP.update(mAP_preds, mAP_labels)

    def compute_confusion(self):
        confusion_mat = self.confusion.compute()

        nc1, nc2 = confusion_mat.shape
        assert nc1 == nc2 == self.num_classes

        L = []
        for i in range(nc1):
            for j in range(nc2):
                # annoyingly, wandb will sort the matrix by row/col names. sad!
                # fix the order we want by prepending the index of the class.
                L.append(
                    (
                        f"{i} - {self.class_names[i]}",
                        f"{j} - {self.class_names[j]}",
                        confusion_mat[i, j],
                    )
                )

        return L

    def compute(self): return self.mAP.compute(), self.compute_confusion()

    def reset(self):
        self.mAP.reset()
        self.confusion.reset()

    def _format_preds_and_labels(
        self,
        batch_preds: torch.Tensor,
        batch_labels: torch.Tensor,
        objectness_thresh: float = 0,
        IoU_thresh: float = 0,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """ A very important utility function for filtering predictions on labels

        Often, we need to calculate conditional probabilites - e.g. #(correct predictions | objectness > thresh)
        We want to select our predicted bbs and class predictions on IOU, and sometimes on ojbectness, e.t.c

        batch_preds and batch_labels are the batch label and prediction tensors.
        objectness_thresh is the "objectness" threshold, YOGO's confidence that there is a prediction in the given cell
        IoU_thresh is the threshold of IoU for prediction and label bbs. 

        Returns (tensor of predictions shape=[N, x y x y t0 *classes], tensor of labels shape=[N, mask x y x y class])
        """
        if IoU_thresh != 0:
            # it isn't immediately obvious to me how exactly to do this. Filter out rows of IoU matrix?
            # what happens if number of predicted_boxes != number of label_boxes? 
            raise NotImplementedError("axel hasn't implemented objectness_threshold yet!")
        if not (0 <= objectness_thresh < 1):
            raise ValueError(f"must have 0 <= objectness_thresh < 1; got objectness_thresh={objectness_thresh}")

        bs, pred_shape, Sy, Sx = batch_preds.shape
        bs, label_shape, Sy, Sx = batch_labels.shape

        # xc yc w h to *classes
        reformatted_preds = (
            batch_preds.permute(1, 0, 2, 3)
            .reshape(pred_shape, bs * Sx * Sy)
            .T
        )

        # mask x y x y class
        reformatted_labels = (
            batch_labels.permute(1, 0, 2, 3)
            .reshape(label_shape, bs * Sx * Sy)
            .T
        )

        # masked labels is *actual predictions*
        label_mask = reformatted_labels[:, 0:1].bool()
        masked_labels = torch.masked_select(reformatted_labels, label_mask)

        # filter on objectness
        preds_with_objects = torch.masked_select(reformatted_preds, (reformatted_preds[:, 4] > objectness_thresh).bool())

        preds_with_objects[:, 0:4] = ops.box_convert(preds_with_objects[:, 0:4], "xcycwh", "xyxy")

        # choose predictions from argmaxed IoU along label dim to get best prediction per label
        prediction_indices = ops.box_iou(masked_labels[:, 1:5], preds_with_objects[:, 0:4]).argmax(dim=0)

        masked_predictions = preds_with_objects[prediction_indices]

        return masked_predictions, masked_labels

    def format_for_confusion(
        self, batch_preds, batch_labels
    ) -> Tuple[List[Dict[str, torch.Tensor]], List[Dict[str, torch.Tensor]]]:
        preds, labels = self._format_preds_and_labels(batch_preds, batch_labels)
        return preds[:, 0:4], labels[:, 1:5]

    @staticmethod
    def format_for_mAP(
        batch_preds, batch_labels
    ) -> Tuple[List[Dict[str, torch.Tensor]], List[Dict[str, torch.Tensor]]]:
        bs, label_shape, Sy, Sx = batch_labels.shape
        bs, pred_shape, Sy, Sx = batch_preds.shape

        device = batch_preds.device
        preds, labels = [], []
        for b, (img_preds, img_labels) in enumerate(zip(batch_preds, batch_labels)):
            if torch.all(img_labels[0, ...] == 0).item():
                # mask says there are no labels!
                labels.append(
                    {
                        "boxes": torch.tensor([], device=device),
                        "labels": torch.tensor([], device=device),
                    }
                )
                preds.append(
                    {
                        "boxes": torch.tensor([], device=device),
                        "labels": torch.tensor([], device=device),
                        "scores": torch.tensor([], device=device),
                    }
                )
            else:
                # view -> T keeps tensor as a view, and no copies?
                row_ordered_img_preds = img_preds.view(-1, Sy * Sx).T
                row_ordered_img_labels = img_labels.view(-1, Sy * Sx).T

                # if label[0] == 0, there is no box in cell Sx/Sy - mask those out
                mask = row_ordered_img_labels[..., 0] == 1

                labels.append(
                    {
                        "boxes": ops.box_convert(
                            row_ordered_img_labels[mask, 1:5], "xyxy", "cxcywh"
                        ),
                        "labels": row_ordered_img_labels[mask, 5],
                    }
                )
                preds.append(
                    {
                        "boxes": row_ordered_img_preds[mask, :4],
                        "scores": row_ordered_img_preds[mask, 4],
                        "labels": torch.argmax(row_ordered_img_preds[mask, 5:], dim=1),
                    }
                )

        return preds, labels


def draw_rects(
    img: torch.Tensor, rects: Union[torch.Tensor, List], thresh: Optional[float] = None
) -> Image:
    """
    img is the torch tensor representing an image
    rects is either
        - a torch.tensor of shape (pred, Sy, Sx), where pred = (xc, yc, w, h, confidence, ...)
        - a list of (class, xc, yc, w, h)
    thresh is a threshold for confidence when rects is a torch.Tensor
    """
    assert (
        len(img.shape) == 2
    ), f"takes single grayscale image - should be 2d, got {img.shape}"
    h, w = img.shape

    if isinstance(rects, torch.Tensor):
        pred_dim, Sy, Sx = rects.shape
        if thresh is None:
            thresh = 0.5
        rects = [r for r in rects.reshape(pred_dim, Sx * Sy).T if r[4] > thresh]
        formatted_rects = [
            [
                int(w * (r[0] - r[2] / 2)),
                int(h * (r[1] - r[3] / 2)),
                int(w * (r[0] + r[2] / 2)),
                int(h * (r[1] + r[3] / 2)),
                torch.argmax(r[5:]).item(),
            ]
            for r in rects
        ]
    elif isinstance(rects, list):
        if thresh is not None:
            raise ValueError("threshold only valid for tensor (i.e. prediction) input")
        formatted_rects = [
            [
                int(w * (r[1] - r[3] / 2)),
                int(h * (r[2] - r[4] / 2)),
                int(w * (r[1] + r[3] / 2)),
                int(h * (r[2] + r[4] / 2)),
                r[0],
            ]
            for r in rects
        ]

    image = T.ToPILImage()(img[None, ...])
    rgb = Image.new("RGB", image.size)
    rgb.paste(image)
    draw = ImageDraw.Draw(rgb)

    for r in formatted_rects:
        draw.rectangle(r[:4], outline="red")
        draw.text((r[0], r[1]), str(r[4]), (0, 0, 0))

    return rgb


if __name__ == "__main__":
    import sys

    from matplotlib.pyplot import imshow, show
    from pathlib import Path

    from yogo.dataloader import get_dataloader
    from yogo.data_transforms import RandomVerticalCrop

    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path to image or dir of images>")
        sys.exit(1)

    path_to_ddf = sys.argv[1]
    ds = get_dataloader(path_to_ddf, batch_size=1, training=False,)

    for img, label in ds["val"]:
        imshow(draw_rects(img[0, 0, ...], list(label[0])))
        show()
