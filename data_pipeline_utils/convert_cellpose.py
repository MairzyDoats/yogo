#! /usr/bin/env python3

import sys
import time
import glob

import numpy as np
import multiprocessing as mp

from tqdm import tqdm
from pathlib import Path
from functools import partial
from cellpose import utils, io

from _utils import normalize, convert_coords, multiprocess_directory_work


def process_cellpose_results(files, output_dir, label=0):
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    work_fcn = partial(work, label, output_dir_path)

    multiprocess_directory_work(files, work_fcn)


def work(label, output_dir_path, f):
    outlines = load_cellpose_npy_file(f)
    file_name = Path(f).name.replace("_seg", "")
    new_csv = (output_dir_path / file_name).with_suffix(".csv")

    with open(new_csv, "w") as g:
        for outline in outlines:
            xmin, xmax, ymin, ymax = (
                outline[:, 0].min(),
                outline[:, 0].max(),
                outline[:, 1].min(),
                outline[:, 1].max(),
            )
            xcenter, ycenter, width, height = convert_coords(xmin, xmax, ymin, ymax)
            g.write(f"{label},{xcenter},{ycenter},{width},{height}\n")


def load_cellpose_npy_file(f):
    data = np.load(f, allow_pickle=True).item()
    return utils.outlines_list(data["masks"])


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"usage: {sys.argv[0]} <input dir> <label dir>")
        sys.exit(1)

    try:
        label = sys.argv[3]
    except IndexError:
        label = 0

    files = glob.glob(f"{sys.argv[1]}/*.npy")
    process_cellpose_results(files, sys.argv[2], label=label)