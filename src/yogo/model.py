import torch
from torch import nn

from typing import Tuple


class YOGO(nn.Module):
    """
    Restricting assumptions:
        - all objects being detected are roughly the same size (K-Means Clustering anchor
        boxes across the dataset verifies this), meaning that it does not make sense to
        have more than 1 anchor box
        - grayscale

    TODO: We do messy stuff here w/r/t inference vs. training mode. While training, we
    want to set self.training=False occasionally (batchnorm and dropout behaviour is
    different during inference), but we still want to use the yogo_loss function to
    measure validation and test, so we do not want to convert to sigmoids or whatever
    else.

    A better way to do this would be to have an "inference" method, that you could plug
    onto the end of forward if we are running inference.
    """

    MODEL_VERSION = "0.0.1"

    def __init__(self, img_size, anchor_w, anchor_h, num_classes=4, inference=False):
        super().__init__()
        self.device = "cpu"

        self.model = self.gen_model(num_classes=num_classes)

        self.register_buffer("img_size", torch.tensor(img_size))
        self.register_buffer("anchor_w", torch.tensor(anchor_w))
        self.register_buffer("anchor_h", torch.tensor(anchor_h))
        self.register_buffer("num_classes", torch.tensor(num_classes))
        # self.register_buffer("model_ver", torch.tensor(self.MODEL_VERSION))

        self.inference = inference

        self._Cxs = None
        self._Cys = None

    @classmethod
    def from_pth(cls, loaded_pth, inference=False):
        params = loaded_pth["model_state_dict"]

        try:
            model_ver = params["model_ver"]
        except KeyError:
            # just assume that the pth file is compatible
            # TODO remove after it is probable that no more pth files w/o versions exist
            model_ver = cls.MODEL_VERSION

        if model_ver != cls.MODEL_VERSION:
            raise ValueError(
                f"pth version is {model_ver}, but the model is version {cls.MODEL_VERSION}"
            )

        img_size = params["img_size"]
        anchor_w = params["anchor_w"]
        anchor_h = params["anchor_h"]
        num_classes = params["num_classes"]

        model = cls(
            (img_size[0], img_size[1]),
            anchor_w.item(),
            anchor_h.item(),
            num_classes=num_classes.item(),
            inference=inference,
        )

        # set Sx, Sy
        assert model._Cxs is None and model._Cys is None
        dummy_input = torch.rand(1, 1, *img_size)
        model(dummy_input)
        assert model._Cxs is not None and model._Cys is not None

        model.load_state_dict(params)
        return model

    def to(self, device):
        self.device = device
        super().to(device, non_blocking=True, dtype=torch.float32)
        return self

    def num_params(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    def grad_norm(self) -> float:
        # https://discuss.pytorch.org/t/check-the-norm-of-gradients/27961/5
        total_norm = 0
        parameters = [
            p for p in self.parameters() if p.grad is not None and p.requires_grad
        ]
        for p in parameters:
            param_norm = p.grad.detach().data.norm(2)
            total_norm += param_norm.item() ** 2
        total_norm = total_norm**0.5
        return total_norm

    def get_grid_size(self, input_shape: Tuple[int, int]) -> Tuple[int, int]:
        """return Sx, Sy
        FIXME - hacky cause we have to infer, should be able to calc from model defn
        """
        out = self(torch.rand(1, 1, *input_shape, device=self.device))
        _, _, Sy, Sx = out.shape
        return Sx, Sy

    def gen_model(self, num_classes) -> nn.Module:
        conv_block_1 = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1, bias=False),
            nn.BatchNorm2d(16),
            nn.LeakyReLU(),
            nn.MaxPool2d(2, stride=2),
            nn.Dropout2d(p=0.2),
        )
        conv_block_2 = nn.Sequential(
            nn.Conv2d(16, 32, 3, padding=1),
            nn.LeakyReLU(),
            nn.MaxPool2d(2, stride=2),
            nn.Dropout2d(p=0.2),
        )
        conv_block_3 = nn.Sequential(
            nn.Conv2d(32, 64, 3, padding=1),
            nn.LeakyReLU(),
            nn.MaxPool2d(2, stride=2),
            nn.Dropout2d(p=0.2),
        )
        conv_block_4 = nn.Sequential(
            nn.Conv2d(64, 128, 3, padding=1),
            nn.LeakyReLU(),
            nn.Dropout2d(p=0.2),
        )
        conv_block_5 = nn.Sequential(
            nn.Conv2d(128, 128, 3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(128),
            nn.LeakyReLU(),
        )
        conv_block_6 = nn.Sequential(
            nn.Conv2d(128, 128, 3, padding=1),
            nn.BatchNorm2d(128),
            nn.LeakyReLU(),
        )
        conv_block_7 = nn.Sequential(
            nn.Conv2d(128, 128, 3, padding=1),
            nn.LeakyReLU(),
        )
        conv_block_8 = nn.Conv2d(128, 5 + num_classes, 1)
        return nn.Sequential(
            conv_block_1,
            conv_block_2,
            conv_block_3,
            conv_block_4,
            conv_block_5,
            conv_block_6,
            conv_block_7,
            conv_block_8,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.model(x.float())

        bs, preds, Sy, Sx = x.shape

        if self._Cxs is None or self._Cys is None:
            self._Cxs = (
                torch.linspace(0, 1 - 1 / Sx, Sx)
                .expand(Sy, -1)
                .to(self.device, non_blocking=True)
            )
            self._Cys = (
                torch.linspace(0, 1 - 1 / Sy, Sy)
                .expand(1, -1)
                .transpose(0, 1)
                .expand(Sy, Sx)
                .to(self.device, non_blocking=True)
            )

        if self.inference:
            classification = torch.softmax(x[:, 5:, :, :], dim=1)
        else:
            classification = x[:, 5:, :, :]

        # implementation of "Direct Location Prediction" from YOLO9000 paper
        # Order of meanings:
        #  center of bounding box in x
        #  center of bounding box in y
        #  width of bounding box
        #  height of bounding box
        #  'objectness' score
        return torch.cat(
            (
                (1 / Sx) * torch.sigmoid(x[:, 0:1, :, :]) + self._Cxs,
                (1 / Sy) * torch.sigmoid(x[:, 1:2, :, :]) + self._Cys,
                self.anchor_w * torch.exp(x[:, 2:3, :, :]),
                self.anchor_h * torch.exp(x[:, 3:4, :, :]),
                torch.sigmoid(x[:, 4:5, :, :]),
                *torch.split(classification, 1, dim=1),
            ),
            dim=1,
        )
