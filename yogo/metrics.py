import torch

from typing import Tuple, List, Dict

from torchmetrics import MetricCollection
from torchmetrics.detection.mean_ap import MeanAveragePrecision
from torchmetrics.classification import (
    MulticlassPrecision,
    MulticlassRecall,
    MulticlassConfusionMatrix,
    MulticlassAccuracy,
    MulticlassROC,
    MulticlassCalibrationError,
)

from yogo.utils.prediction_formatting import (
    PredictionLabelMatch,
    format_preds_and_labels_v2,
)


class Metrics:
    @torch.no_grad()
    def __init__(
        self,
        num_classes: int,
        device: str = "cpu",
        sync_on_compute: bool = False,
        min_class_confidence_threshold: float = 0.9,
        include_mAP: bool = True,
    ):
        self.num_classes = num_classes + 1  # add 1 for background
        self.min_class_confidence_threshold = min_class_confidence_threshold
        self.include_mAP = include_mAP

        # map can be very costly; so lets be able to turn it off if we
        # don't need it
        if include_mAP:
            self.mAP = MeanAveragePrecision(
                box_format="xyxy",
                sync_on_compute=sync_on_compute,
            )
            self.mAP.warn_on_many_detections = False
            self.mAP.to(device)

        self.confusion = MulticlassConfusionMatrix(
            num_classes=self.num_classes,
            validate_args=False,
            sync_on_compute=sync_on_compute,
        )
        self.confusion.to(device)

        self.prediction_metrics = MetricCollection(
            [
                MulticlassAccuracy(
                    num_classes=self.num_classes,
                    average=None,
                    validate_args=False,
                    sync_on_compute=sync_on_compute,
                ),
                MulticlassROC(
                    num_classes=self.num_classes,
                    thresholds=500,
                    validate_args=False,
                    sync_on_compute=sync_on_compute,
                ),
                MulticlassPrecision(
                    num_classes=self.num_classes,
                    validate_args=False,
                    sync_on_compute=sync_on_compute,
                ),
                MulticlassRecall(
                    num_classes=self.num_classes,
                    validate_args=False,
                    sync_on_compute=sync_on_compute,
                ),
                MulticlassCalibrationError(
                    num_classes=self.num_classes,
                    n_bins=30,
                    validate_args=False,
                    sync_on_compute=sync_on_compute,
                ),
            ],
        )
        self.prediction_metrics.to(device)

    def update(self, preds, labels, use_IoU: bool = True):
        bs, pred_shape, Sy, Sx = preds.shape
        bs, label_shape, Sy, Sx = labels.shape

        pred_label_matches: PredictionLabelMatch = PredictionLabelMatch.concat(
            [
                format_preds_and_labels_v2(
                    pred,
                    label,
                    use_IoU=use_IoU,
                    min_class_confidence_threshold=self.min_class_confidence_threshold,
                )
                for pred, label in zip(preds, labels)
            ]
        )
        pred_label_matches = pred_label_matches.convert_background_errors(
            self.num_classes
        )
        fps, fls = pred_label_matches.preds, pred_label_matches.labels

        if self.include_mAP:
            self.mAP.update(*self._format_for_mAP(fps, fls))

        self.confusion.update(fps[:, 5:].argmax(dim=1), fls[:, 5:].squeeze())
        self.prediction_metrics.update(fps[:, 5:], fls[:, 5:].squeeze().long())

    def compute(self):
        pr_metrics = self.prediction_metrics.compute()

        if self.include_mAP:
            mAP_metrics = self.mAP.compute()
        else:
            mAP_metrics = {
                "map": torch.tensor(0.0),
            }

        confusion_metrics = self.confusion.compute()

        return (
            mAP_metrics,
            confusion_metrics,
            pr_metrics["MulticlassAccuracy"],
            pr_metrics["MulticlassROC"],
            pr_metrics["MulticlassPrecision"],
            pr_metrics["MulticlassRecall"],
            pr_metrics["MulticlassCalibrationError"].item(),
        )

    def reset(self):
        if self.include_mAP:
            self.mAP.reset()
        self.confusion.reset()
        self.prediction_metrics.reset()

    def forward(self, preds, labels):
        self.update(preds, labels)
        res = self.compute()
        self.reset()
        return res

    def _format_for_mAP(
        self, preds: torch.Tensor, labels: torch.Tensor
    ) -> Tuple[List[Dict[str, torch.Tensor]], List[Dict[str, torch.Tensor]]]:
        """
        formatted_preds
           tensor of predictions shape=[N, x y x y objectness *classes]
        formatted_labels
           tensor of labels shape=[N, mask x y x y class])
        """
        formatted_preds, formatted_labels = [], []

        for fp, fl in zip(preds, labels):
            formatted_preds.append(
                {
                    "boxes": fp[:4].reshape(1, 4),
                    "scores": fp[4].reshape(1),
                    "labels": fp[5:].argmax().reshape(1),
                }
            )
            formatted_labels.append(
                {
                    "boxes": fl[1:5].reshape(1, 4),
                    "labels": fl[5].reshape(1).long(),
                }
            )

        return formatted_preds, formatted_labels
