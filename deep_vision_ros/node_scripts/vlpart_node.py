#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from jsk_topic_tools import ConnectionBasedTransport
from jsk_recognition_msgs.msg import Rect, RectArray
from jsk_recognition_msgs.msg import Label, LabelArray
from jsk_recognition_msgs.msg import ClassificationResult

from vision_anything.config.model_config import VLPartConfig
from vision_anything.model.model_wrapper import VLPartModel


class VLPartNode(ConnectionBasedTransport):
    def __init__(self):
        super(VLPartNode, self).__init__()
        # self.reconfigure_server = Server(ServerConfig, self.config_cb)
        self.vocabulary = rospy.get_param("~vocabulary", "custom")
        self.classes = [
            _class.strip()
            for _class in rospy.get_param("~classes", "bottle cap; cup handle;").split(";")
            if _class.strip()
        ]
        self.confidence_threshold = rospy.get_param("~confidence_threshold", 0.5)
        self.initialize()

        self.bridge = CvBridge()
        self.pub_vis_img = self.advertise("~output/debug_image", Image, queue_size=1)
        self.pub_rects = self.advertise("~output/rects", RectArray, queue_size=1)
        self.pub_labels = self.advertise("~output/labels", LabelArray, queue_size=1)
        self.pub_class = self.advertise("~output/class", ClassificationResult, queue_size=1)
        self.pub_seg = self.advertise("~output/segmentation", Image, queue_size=1)

    def subscribe(self):
        self.sub_image = rospy.Subscriber(
            "~input_image",
            Image,
            self.callback,
            queue_size=1,
            buff_size=2**24,
        )

    def unsubscribe(self):
        self.sub_image.unregister()

    def initialize(self):
        self.detect_flag = False
        self.config = VLPartConfig.from_args(
            model_type=rospy.get_param(
                "~model_type", "swinbase_cascade_lvis_paco_pascalpart_partimagenet_inparsed"
            ),
            device=rospy.get_param("~device", "cuda:0"),
        )
        self.model = VLPartModel(self.config)
        self.model.set_model(self.vocabulary, self.classes, self.confidence_threshold)
        self.detect_flag = True

    def publish_result(self, boxes, label_names, scores, mask, vis, frame_id):
        if label_names is not None:
            label_array = LabelArray()
            label_array.labels = [Label(id=i + 1, name=name) for i, name in enumerate(label_names)]
            label_array.header.stamp = rospy.Time.now()
            label_array.header.frame_id = frame_id
            self.pub_labels.publish(label_array)

            class_result = ClassificationResult(
                header=label_array.header,
                classifier=self.config.model_name,
                target_names=self.classes,
                labels=[self.classes.index(name) for name in label_names],
                label_names=label_names,
                label_proba=scores,
            )
            self.pub_class.publish(class_result)

        if boxes is not None:
            rects = []
            for box in boxes:
                rect = Rect()
                rect.x = int(box[0])  # x1
                rect.y = int(box[1])  # y1
                rect.width = int(box[2] - box[0])  # x2 - x1
                rect.height = int(box[3] - box[1])  # y2 - y1
                rects.append(rect)
            rect_array = RectArray(rects=rects)
            rect_array.header.stamp = rospy.Time.now()
            rect_array.header.frame_id = frame_id
            self.pub_rects.publish(rect_array)

        if vis is not None:
            vis_img_msg = self.bridge.cv2_to_imgmsg(vis, encoding="rgb8")
            vis_img_msg.header.stamp = rospy.Time.now()
            vis_img_msg.header.frame_id = frame_id
            self.pub_vis_img.publish(vis_img_msg)

        if mask is not None:
            seg_msg = self.bridge.cv2_to_imgmsg(mask, encoding="32SC1")
            seg_msg.header.stamp = rospy.Time.now()
            seg_msg.header.frame_id = frame_id
            self.pub_seg.publish(seg_msg)

    def callback(self, img_msg):
        if self.detect_flag:
            image = self.bridge.imgmsg_to_cv2(img_msg, desired_encoding="rgb8")
            detections, segmentation, visualization = self.model.predict(image)
            labels = [self.classes[i] for i in detections.class_id]
            self.publish_result(
                detections.xyxy,
                labels,
                detections.confidence,
                segmentation,
                visualization,
                img_msg.header.frame_id,
            )


if __name__ == "__main__":
    rospy.init_node("vlpart_node")
    node = VLPartNode()
    rospy.spin()
