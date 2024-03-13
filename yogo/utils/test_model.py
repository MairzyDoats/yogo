#! /usr/bin/env python3

import os
import torch
import wandb
import pickle
import argparse
import warnings

import torch.multiprocessing as mp
from torch.utils.data.distributed import DistributedSampler
from torch.utils.data import Dataset, DataLoader

from yogo.model import YOGO
from yogo.train import Trainer
from yogo.data import YOGO_CLASS_ORDERING
from yogo.data.yogo_dataset import ObjectDetectionDataset
from yogo.data.utils import collate_batch_robust
from yogo.data.yogo_dataloader import (
    get_dataloader,
    choose_dataloader_num_workers,
)
from yogo.utils import get_free_port


def test_model(rank: int, world_size: int, args: argparse.Namespace) -> None:
    torch.distributed.init_process_group(
        backend="nccl", rank=rank, world_size=world_size
    )

    y, cfg = YOGO.from_pth(args.pth_path, inference=False)
    y.to("cuda")

    dataloaders = get_dataloader(
        args.dataset_defn_path,
        64,
        y.get_grid_size()[0],
        y.get_grid_size()[1],
        normalize_images=cfg["normalize_images"],
    )

    test_dataset: Dataset[ObjectDetectionDataset] = dataloaders["test"].dataset
    DistributedSampler(
        test_dataset,
        rank=rank,
        num_replicas=world_size,
    )

    num_workers = choose_dataloader_num_workers(len(test_dataset))  # type: ignore

    test_dataloader = DataLoader(
        test_dataset,
        shuffle=False,
        drop_last=False,
        pin_memory=True,
        batch_size=64,
        num_workers=num_workers,
        persistent_workers=num_workers > 0,
        generator=torch.Generator().manual_seed(111111),
        collate_fn=collate_batch_robust,
        multiprocessing_context="spawn" if num_workers > 0 else None,
    )

    config = {
        "class_names": YOGO_CLASS_ORDERING,
        "no_classify": False,
        "iou_weight": 1,
        "healthy_weight": 1,
        "no_obj_weight": 0.5,
        "label_smoothing": 0.0001,
        "half": True,
        "model": args.pth_path,
        "test_set": args.dataset_defn_path,
    }

    if args.wandb or args.wandb_resume_id and rank == 0:
        print("logging to wandb")
        wandb.init(
            project="yogo",
            entity="bioengineering",
            config=config,
            id=args.wandb_resume_id,
            resume="allow",
            tags=args.tags,
            notes=args.note,
        )

        if (wandb.run is not None) and wandb.run.offline:
            warnings.warn(
                "wandb run is offline - will not be logged "
                "to wandb.ai but to the local disc"
            )

        assert wandb.run is not None
        wandb.run.tags += type(wandb.run.tags)(["resumed for test"])

    test_metrics = Trainer.test(
        test_dataloader,
        "cuda",
        config,
        y,
        include_mAP=args.include_mAP,
        include_background=args.include_background,
        formatter=args.prediction_formatter,
    )

    if args.wandb or args.wandb_resume_id and rank == 0:
        Trainer._log_test_metrics(*test_metrics)  # type: ignore

    if args.dump_to_disk and rank == 0:
        pickle.dump(test_metrics, open("test_metrics.pkl", "wb"))


def do_model_test(args):
    world_size = torch.cuda.device_count()
    if world_size == 0:
        raise RuntimeError(
            "at least 1 gpu is required for testing (otherwise it's painfully slow); "
            "if cpu training is required, we can add it back"
        )

    os.environ["MASTER_ADDR"] = "0.0.0.0"
    os.environ["MASTER_PORT"] = str(get_free_port())
    mp.spawn(test_model, args=(world_size, args), nprocs=world_size, join=True)
