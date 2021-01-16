#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import types
import cv2
import numpy as np
from numpy import random
import torch
from torchvision import transforms

def intersect(box_a, box_b):
    max_xy = np.minimum(box_a[:, 2:], box_b[2:])
    min_xy = np.maximum(box_a[:, :2], box_b[:2])
    inter = np.clip((max_xy - min_xy), a_min=0, a_max=np.inf)
    return inter[:, 0] * inter[:, 1]

def jaccard_numpy(box_a, box_b):

    inter = intersect(box_a, box_b)
    area_a = ((box_a[:, 2]-box_a[:, 0]) *
              (box_a[:, 3]-box_a[:, 1]))  # [A,B]
    area_b = ((box_b[2]-box_b[0]) *
              (box_b[3]-box_b[1]))  # [A,B]
    union = area_a + area_b - inter

    return inter / union  # [A,B]


class Compose(object):

    def __init__(self, transforms):

        self.transforms = transforms

    def __call__(self, img, boxes=None, labels=None):

        for t in self.transforms:
            img, boxes, labels = t(img, boxes, labels)

        return img, boxes, labels


class Lambda(object):

    def __init__(self, lambd):

        assert isinstance(lambd, types.LambdaType)
        self.lambd = lambd

    def __call__(self, img, boxes=None, labels=None):

        return self.lambd(img, boxes, labels)


class ConvertFromInts(object):

    def __call__(self, image, boxes=None, labels=None):

        return image.astype(np.float32), boxes, labels


class SubtractMeans(object):

    def __init__(self, mean):

        self.mean = np.array(mean, dtype=np.float32)


    def __call__(self, image, boxes=None, labels=None):

        image = image.astype(np.float32)
        image -= self.mean

        return image.astype(np.float32), boxes, labels


class ToAbsoluteCoords(object):

    def __call__(self, image, boxes=None, labels=None):

        height, width, _ = image.shape
        boxes[:, 0] *= width
        boxes[:, 2] *= width
        boxes[:, 1] *= height
        boxes[:, 3] *= height

        return image, boxes, labels


class ToPercentCoords(object):

    def __call__(self, image, boxes=None, labels=None):

        height, width, _ = image.shape
        boxes[:, 0] /= width
        boxes[:, 2] /= width
        boxes[:, 1] /= height
        boxes[:, 3] /= height

        return image, boxes, labels


class Resize(object):

    def __init__(self, size=300):

        self.size = size


    def __call__(self, image, boxes=None, labels=None):

        image = cv2.resize(image, (self.size, self.size))

        return image, boxes, labels


class RandomSaturation(object):

    def __init__(self, lower=0.5, upper=1.5):

        self.lower = lower
        self.upper = upper
        assert self.upper >= self.lower, 'Contrast upper must be >= lower.'
        assert self.lower >= 0, 'Contrast lower must be non-negative.'


    def __call__(self, image, boxes=None, labels=None):

        if random.randint(2):
            image[:, :, 1] *= random.uniform(self.lower, self.upper)

        return image, boxes, labels


class RandomHue(object):

    def __init__(self, delta=18.0):

        assert delta >= 0.0 and delta <= 360.0
        self.delta = delta

    def __call__(self, image, boxes=None, labels=None):

        if random.randint(2):
            image[:, :, 0] += random.uniform(-self.delta, self.delta)
            image[:, :, 0][image[:, :, 0] > 360.0] -= 360.0
            image[:, :, 0][image[:, :, 0] < 0.0] += 360.0

        return image, boxes, labels


class RandomLightingNoise(object):

    def __init__(self):

        self.perms = ((0, 1, 2), (0, 2, 1),
                      (1, 0, 2), (1, 2, 0),
                      (2, 0, 1), (2, 1, 0))

    def __call__(self, image, boxes=None, labels=None):

        if random.randint(2):
            swap = self.perms[random.randint(len(self.perms))]
            shuffle = SwapChannels(swap) # Shuffle channels
            image = shuffle(image)

        return image, boxes, labels


class ConvertColor(object):

    def __init__(self, current='BGR', transform='HSV'):

        self.transform = transform
        self.current = current


    def __call__(self, image, boxes=None, labels=None):

        if self.current == 'BGR' and self.transform == 'HSV':
            image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        elif self.current == 'HSV' and self.transform == 'BGR':
            image = cv2.cvtColor(image, cv2.COLOR_HSV2BGR)
        else:
            raise NotImplementedError

        return image, boxes, labels


class RandomContrast(object):

    def __init__(self, lower=0.5, upper=1.5):

        self.lower = lower
        self.upper = upper
        assert self.upper >= self.lower, 'Contrast upper must be >= lower.'
        assert self.lower >= 0, 'Contrast lower must be non-negative.'

    def __call__(self, image, boxes=None, labels=None):

        if random.randint(2):
            alpha = random.uniform(self.lower, self.upper)
            image *= alpha

        return image, boxes, labels


class RandomBrightness(object):

    def __init__(self, delta=32):

        assert delta >= 0.0
        assert delta <= 255.0
        self.delta = delta


    def __call__(self, image, boxes=None, labels=None):

        if random.randint(2):
            delta = random.uniform(-self.delta, self.delta)
            image += delta

        return image, boxes, labels


class ToCV2Image(object):

    def __call__(self, tensor, boxes=None, labels=None):

        return tensor.cpu().numpy().astype(np.float32).transpose((1, 2, 0)), boxes, labels


class ToTensor(object):

    def __call__(self, cvimage, boxes=None, labels=None):

        return torch.from_numpy(cvimage.astype(np.float32)).permute(2, 0, 1), boxes, labels


class RandomSampleCrop(object):

    def __init__(self):

        self.sample_options = (
            # Using entire original input image
            None,
            # Sample a patch s.t. MIN jaccard with obj in .1,.3,.4,.7,.9
            (0.1, None),
            (0.3, None),
            (0.7, None),
            (0.9, None),
            # Randomly sample a patch
            (None, None),
        )

    def __call__(self, image, boxes=None, labels=None):

        height, width, _ = image.shape

        while True:
            # Randomly choose a mode
            mode = random.choice(self.sample_options)
            if mode is None:
                return image, boxes, labels

            min_iou, max_iou = mode
            if min_iou is None:
                min_iou = float('-inf')
            if max_iou is None:
                max_iou = float('inf')

            # Max trails (50)
            for _ in range(50):
                current_image = image

                w = random.uniform(0.3 * width, width)
                h = random.uniform(0.3 * height, height)

                # Aspect ratio constraint b/t .5 & 2
                if h / w < 0.5 or h / w > 2:
                    continue

                left = random.uniform(width - w)
                top = random.uniform(height - h)

                # Convert to integer rect x1,y1,x2,y2
                rect = np.array([int(left), int(top), int(left+w), int(top+h)])

                # Calculate IoU (jaccard overlap) b/t the cropped and gt boxes
                overlap = jaccard_numpy(boxes, rect)

                # Is min and max overlap constraint satisfied? If not try again
                if overlap.min() < min_iou and max_iou < overlap.max():
                    continue

                # Cut the crop from the image
                current_image = current_image[rect[1]:rect[3], rect[0]:rect[2],
                                              :]

                # Keep overlap with gt box if center in sampled patch
                centers = (boxes[:, :2] + boxes[:, 2:]) / 2.0

                # Mask in all gt boxes that above and to the left of centers
                m1 = (rect[0] < centers[:, 0]) * (rect[1] < centers[:, 1])

                # Mask in all gt boxes that under and to the right of centers
                m2 = (rect[2] > centers[:, 0]) * (rect[3] > centers[:, 1])

                # Mask in that both m1 and m2 are true
                mask = m1 * m2

                # Have any valid boxes? try again if not
                if not mask.any():
                    continue

                # Take only matching gt boxes
                current_boxes = boxes[mask, :].copy()

                # Take only matching gt labels
                current_labels = labels[mask]

                # Should we use the box left and top corner or the crop's
                current_boxes[:, :2] = np.maximum(current_boxes[:, :2], rect[:2])

                # Adjust to crop (by substracting crop's left,top)
                current_boxes[:, :2] -= rect[:2]
                current_boxes[:, 2:] = np.minimum(current_boxes[:, 2:], rect[2:])
                
                # Adjust to crop (by substracting crop's left,top)
                current_boxes[:, 2:] -= rect[:2]

                return current_image, current_boxes, current_labels


class Expand(object):

    def __init__(self, mean):

        self.mean = mean

    def __call__(self, image, boxes, labels):

        if random.randint(2):
            return image, boxes, labels

        height, width, depth = image.shape
        ratio = random.uniform(1, 4)
        left = random.uniform(0, width*ratio - width)
        top = random.uniform(0, height*ratio - height)

        expand_image = np.zeros((int(height*ratio), int(width*ratio), depth), dtype=image.dtype)
        expand_image[:, :, :] = self.mean
        expand_image[int(top):int(top + height), int(left):int(left + width)] = image
        image = expand_image

        boxes = boxes.copy()
        boxes[:, :2] += (int(left), int(top))
        boxes[:, 2:] += (int(left), int(top))

        return image, boxes, labels


class RandomMirror(object):

    def __call__(self, image, boxes, classes):

        _, width, _ = image.shape

        if random.randint(2):
            image = image[:, ::-1]
            boxes = boxes.copy()
            boxes[:, 0::2] = width - boxes[:, 2::-2]

        return image, boxes, classes


class SwapChannels(object):

    def __init__(self, swaps):

        self.swaps = swaps

    def __call__(self, image):

        image = image[:, :, self.swaps]

        return image


class PhotometricDistort(object):

    def __init__(self):

        self.pd = [
            RandomContrast(),
            ConvertColor(transform='HSV'),
            RandomSaturation(),
            RandomHue(),
            ConvertColor(current='HSV', transform='BGR'),
            RandomContrast()
        ]
        self.rand_brightness = RandomBrightness()
        self.rand_light_noise = RandomLightingNoise()

    def __call__(self, image, boxes, labels):

        im = image.copy()
        im, boxes, labels = self.rand_brightness(im, boxes, labels)
        if random.randint(2):
            distort = Compose(self.pd[:-1])
        else:
            distort = Compose(self.pd[1:])
        im, boxes, labels = distort(im, boxes, labels)

        return self.rand_light_noise(im, boxes, labels)