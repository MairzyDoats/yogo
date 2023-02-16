# You Only Glance Once (YOGO) Architecture


## Intro

Real-time object detection is a difficult challenge. In general, object detection requires significant compute requirements. The scale of these compute requirements vary depending on the specific architecture of the object detector. For example, deformable parts models (DPMs) scanned a classifier over an image at multiple scales. An improvement on this is the R-CNN family of models, which propose regions of the image that are then sent to the classifier, reducing the number of classification inferences required. These are "Two-Stage Detectors".

One-Stage Detectors, such as the YOLO family, Single Shot MultiBox Detector, and RetinaNet, produce their predictions in one forward pass of the network. They are generally faster than two-stage detectors with similar (or better) accuracy. Their speed makes them a natural choice for real-time object detection.

For our application of diagnosing malaria, we chose to work off of the YOLO family of networks, originally created py Joseph Redmon and Ali Farhadi (https://pjreddie.com/). The architecture of the YOGO network is a simplification of the YOLO networks (specifically YOLO versions 1-3) optimized for our application.

This document will discuss the YOGO architecture and how it is different from some of the YOLO architectures. First, though, we must understand the specifics of our problem (diagnosing malaria) compared to object detection datasets.

## On Diagnosing Malaria

Our specific application of diagnosing malaria is a much simpler problem (in terms of object detection) than typical object detection problems, due to the low number of classes and uniform sizes of all objects. Most object detectors are designed to perform well on large and varied datasets such as MS COCO, which has 80 classes with objects varying in size, shape, and position within the image.

For example, below is an image of malarial blood (100x magnification):

![malarial blood](imgs/100x_bb_preds.png)


And here is an example of an image from the [YOLO9000 Paper](https://arxiv.org/pdf/1612.08242.pdf) (not necessarily in the MS COCO dataset):

<img src="imgs/yolo9000_example.png" width="400">

Notice the varying sizes of scale for people and the large number of classes - there are "athletes", "contestants", and "unicycles" in this picture. A typical, smaller dataset would have just classified "athletes" and "contestants" as "people".

The relative simplicity of our problem allows us to strip back a lot of the complexity of a typical YOLO architecture.


## YOGO Architecture

The YOGO architecture is relatively simple convolutional network. The specifics of the architecture are changing frequently, as it is still under development, but the core ideas remain constant. The network can be broken into two main components: the Backbone and the Head.

The Backbone processes the input image into a feature map that represents the image. It is 6 layers of convolutions with batchnorm and dropout for regularization, max pool layers to downsample, and Leaky ReLU activations. The Head is a convolutional layer which converts the feature map into the output tensor. The output tensor contains a grid of predictions.

The following sections will discuss the details of this section. It will be a little bit out of order, but I think that this is the right ordering.

### Prediction Grid



### Anchors and Predictions

Before anything else, we must understand what a prediction actually is. The prediction of a bounding box is broken into 5 numbers ($t_x$, $t_y$, $t_w$, $t_h$, $t_o$) and class predictions ($\mathbb{c}$). One important thing to note is that the values $t_x$, $t_y$, $t_w$, $t_h$ are not **direct predictions** of the bounding box. They are used in the following equations to interpret the bounding box:

<img src="imgs/prediction_format.png" width="400">

- $t_x$ and $t_y$ are the x and y centers of the bounding box, normalized to the width and height of the image (so they are between 0 and 1)
- $t_w$ and $t_h$ are the width and height, also normalized
- $t_o$ is the "objectness" of the prediction - this can be considered the confidence of this prediction, and this is also between 0 and 1
- $\mathbb{c}$ is a vector of your normal class predictions (softmax'ed)

They are

## Great related sources

https://www.jeremyjordan.me/object-detection-one-stage/