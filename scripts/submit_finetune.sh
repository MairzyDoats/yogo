#! /usr/bin/env bash

sbatch scripts/submit_cmd_multi_gpu.sh yogo train \
   ../dataset_defs/human-labels/all-dataset-subsets-no-aug.yml \
   --from-pretrained trained_models/vibrant-rooster-557/best.pth \
   --lr 5e-5 \
   --batch-size 64 \
   --epochs 128 \
   --label-smoothing 5e-3 \
   --weight-decay 5e-3 \
   --no-obj-weight 1 \
   --note "quarter_filters" \
   --lr-decay-factor 16 \
   --model quarter_filters \
   --tags scaling-law no-aug \
   --normalize-images

sbatch scripts/submit_cmd_multi_gpu.sh yogo train \
   ../dataset_defs/human-labels/all-dataset-subsets-no-aug.yml \
   --from-pretrained trained_models/vermilion-noodles-558/best.pth \
   --lr 5e-5 \
   --batch-size 64 \
   --epochs 128 \
   --label-smoothing 5e-3 \
   --weight-decay 5e-3 \
   --no-obj-weight 1 \
   --note "half_filters" \
   --lr-decay-factor 16 \
   --model half_filters \
   --tags scaling-law no-aug \
   --normalize-images

sbatch scripts/submit_cmd_multi_gpu.sh yogo train \
   ../dataset_defs/human-labels/all-dataset-subsets-no-aug.yml \
   --from-pretrained trained_models/fortuitous-orchid-553/best.pth \
   --lr 5e-5 \
   --batch-size 64 \
   --epochs 128 \
   --label-smoothing 5e-3 \
   --weight-decay 5e-3 \
   --no-obj-weight 1 \
   --note "base" \
   --lr-decay-factor 16 \
   --model base_model \
   --tags scaling-law no-aug \
   --normalize-images

sbatch scripts/submit_cmd_multi_gpu.sh yogo train \
   ../dataset_defs/human-labels/all-dataset-subsets-no-aug.yml \
   --from-pretrained trained_models/sparkling-paper-555/best.pth \
   --lr 5e-5 \
   --batch-size 64 \
   --epochs 128 \
   --label-smoothing 5e-3 \
   --weight-decay 5e-3 \
   --no-obj-weight 1 \
   --note "double_filters" \
   --lr-decay-factor 16 \
   --model double_filters \
   --tags scaling-law no-aug \
   --normalize-images

sbatch scripts/submit_cmd_multi_gpu.sh yogo train \
   ../dataset_defs/human-labels/all-dataset-subsets-no-aug.yml \
   --from-pretrained trained_models/crimson-mandu-556/best.pth \
   --lr 5e-5 \
   --batch-size 32 \
   --epochs 128 \
   --label-smoothing 5e-3 \
   --weight-decay 5e-3 \
   --no-obj-weight 1 \
   --note "triple_filters" \
   --lr-decay-factor 16 \
   --model triple_filters \
   --tags scaling-law no-aug no-aug \
   --normalize-images