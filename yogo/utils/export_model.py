#! /usr/bin/env python3

import subprocess

import onnx
import onnxsim
import onnxruntime

import torch

import numpy as np

from pathlib import Path

from yogo.model import YOGO
from yogo.utils.argparsers import export_parser


"""
Learning from https://pytorch.org/tutorials/advanced/super_resolution_with_onnxruntime.html
"""


def to_numpy(tensor):
    return (
        tensor.detach().cpu().numpy() if tensor.requires_grad else tensor.cpu().numpy()
    )


class YOGOWrap(YOGO):
    """
    we can normalize images within YOGO here, so we don't have to do it in ulc-malaria-scope
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.normalize_images = False

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # we get either raw uint8 tensors or float tensors
        if x.ndim == 3:
            x.unsqueeze_(0)

        x = x.float()
        if self.normalize_images:
            x /= 255.0

        return super().forward(x)


def do_export(args):
    pth_filename = args.input
    onnx_filename = Path(
        args.output_filename
        if args.output_filename is not None
        else pth_filename.replace("pth", "onnx")
    ).with_suffix(".onnx")

    # the original model
    net, cfg = YOGO.from_pth(pth_filename, inference=True)
    net.normalize_images = cfg["normalize_images"]
    net.eval()

    # the wrapped model, that we'll export
    net_wrap = YOGOWrap(
        net.img_size, net.anchor_w, net.anchor_h, net.num_classes, inference=True
    )
    net_wrap.load_state_dict(net.state_dict())
    net_wrap.eval()

    img_h, img_w = net.img_size
    dummy_input = torch.randint(0, 256, (1, 1, int(img_h.item()), int(img_w.item())))

    # make sure we didn't mess up the wrap!
    torch.allclose(
        net(dummy_input.float() / 255.0 if net.normalize_images else dummy_input),
        net_wrap(dummy_input),
        rtol=1e-3,
        atol=1e-5,
    )

    if args.crop_height is not None:
        img_h = (args.crop_height * img_h).round()
        net_wrap.resize_model(img_h.item())

    torch.onnx.export(
        net_wrap,
        dummy_input,
        str(onnx_filename),
        verbose=False,
        do_constant_folding=True,
        opset_version=17,
    )

    # Load the ONNX model
    model_candidate = onnx.load(str(onnx_filename))

    if args.simplify:
        model_simplified_candidate, model_simplified_OK = onnxsim.simplify(
            model_candidate
        )
        model = model_simplified_candidate if model_simplified_OK else model_candidate
    else:
        model = model_candidate

    # Check that the model is well formed
    onnx.checker.check_model(model)

    # Compare model output from pure torch and onnx
    ort_session = onnxruntime.InferenceSession(str(onnx_filename))
    ort_inputs = {ort_session.get_inputs()[0].name: to_numpy(dummy_input)}
    ort_outs = ort_session.run(None, ort_inputs)

    np.testing.assert_allclose(
        to_numpy(net_wrap(dummy_input)),
        ort_outs[0],
        rtol=1e-3,
        atol=1e-5,
        err_msg="onnx and pytorch outputs are far apart",
    )

    success_msg = f"exported to {str(onnx_filename)}"

    # export to IR
    subprocess.run(
        [
            "mo",
            "--input_model",
            str(onnx_filename),
            "--output_dir",
            onnx_filename.resolve().parents[0],
            "--compress_to_fp16",
            "True",
        ],
        stdout=subprocess.DEVNULL,
    )
    success_msg += f", {str(onnx_filename.with_suffix('.xml'))}, {str(onnx_filename.with_suffix('.bin'))}"

    print(success_msg)


if __name__ == "__main__":
    parser = export_parser()
    args = parser.parse_args()

    try:
        do_export(args)
    except AttributeError:
        parser.print_help()
