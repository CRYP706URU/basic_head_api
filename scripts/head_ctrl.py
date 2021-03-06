#!/usr/bin/env python
# Copyright (c) 2013-2018 Hanson Robotics, Ltd, all rights reserved 
import os
import yaml
from collections import OrderedDict
from os.path import basename
import time

import rospy
from basic_head_api import FaceExpr
from basic_head_api import Quat
from basic_head_api.animation import Animation
from basic_head_api.playback import Playback
from basic_head_api.srv import *
from geometry_msgs.msg import Quaternion
from hr_msgs.msg import PointHead, PlayAnimation, MotorCommand, pau, MakeFaceExpr, TargetPosture
from std_msgs.msg import Float64, String

def to_dict(list, key):
    result = {}
    for entry in list:
        result[entry[key]] = entry
    return result

class PauCtrl:

    def point_head(self, req):
        msg = pau()
        msg.m_headRotation = Quaternion(
            *Quat.Quat.fromInYZX(req.roll, -req.yaw, -req.pitch).params
        )
        self.pub_neck.publish(msg)

    def __init__(self):
        # PAU commands will be sent to these publishers
        self.pub_neck = rospy.Publisher("cmd_neck_pau", pau, queue_size=30)


class SpecificRobotCtrl:

    def valid_exprs(self):
        return {"exprnames": [x for x in self.faces.keys() if x[:4] != "vis_"]}

    def make_face(self, exprname, intensity=1):
        try:
            for cmd in self.faces[exprname].new_msgs(intensity):
                if exprname[:4] == 'vis_':
                    cmd.speed = 0.2
                    cmd.acceleration = 0.1
                self.publisher(cmd)
        except KeyError:
            rospy.logerr("Cant find expression {}".format(exprname))

    def publisher(self, cmd):
        (cmd.joint_name, pubid, hardware) = cmd.joint_name.split('@')
        # Dynamixel commands only sends position
        if hardware == 'dynamixel':
            t = TargetPosture()
            t.names.append(cmd.joint_name)
            t.values.append(cmd.position)
            self.publishers['dynamixels'].publish(t)
        else:
            self.publishers[pubid].publish(cmd)


    def play_animation(self, animation, fps):
        self.playback.play(self.animations[animation],fps, animation)

    def animation_length(self, req):
        if req.name in self.animations.keys():
            return AnimationLengthResponse(self.animations[req.name].total)
        else:
            return AnimationLengthResponse(0)

    def __init__(self):
        # Wait for certain amount of time motors to be loaded in param server
        for i in range(1,20):
            if not rospy.get_param('motors_init', False):
                time.sleep(1)
                continue
            break
        motors = rospy.get_param('motors')
        assemblies = rospy.get_param('/assemblies')
        expressions = rospy.get_param('expressions', [])
        animations = rospy.get_param('animations', [])
        #Gather expressions and animations from all assemblies
        for a in assemblies:
            expressions += rospy.get_param('/{}/expressions'.format(basename(a)),[])
            animations += rospy.get_param('/{}/animations'.format(basename(a)),[])
        rospy.set_param('all_expressions',expressions)
        rospy.set_param('all_animations',animations)
        expressions = OrderedDict((v.keys()[0],v.values()[0]) for k,v in enumerate(expressions))
        #Expressions to motors mapping
        self.faces = FaceExpr.FaceExprMotors.from_expr_yaml(expressions, motors)
        # Animation objects

        animations = OrderedDict((v.keys()[0],v.values()[0]) for k,v in enumerate(animations))
        self.animations = Animation.from_yaml(animations)
        # Motor commands will be sent to this publisher.
        self.publishers = {}
        # Prevents from playing two animations with same prefix
        # For example Left and Right arms can be played at same time but not two animations for same arm.
        # loaded from param server in robot config
        self.animationChannels = rospy.get_param('kf_anim_channels', [])
        self.playback = Playback(motors, self.publisher, self.animationChannels)
        # Create motor publishers by robot names
        self.publishers['dynamixels'] = rospy.Publisher("dynamixels",TargetPosture, queue_size=100)
        for m in motors.values():
            if not 'topic' in m:
                continue
            if not m['topic'] in self.publishers.keys():
                # Pololu motor if motor_id is specified
                if m['hardware'] == 'pololu':
                    self.publishers[m['topic']] = rospy.Publisher(m['topic']+"/command",MotorCommand, queue_size=30)

class HeadCtrl:

    def valid_face_exprs(self,req):
        return self.robot_ctrl.valid_exprs()

    def face_request(self, req):
        self.robot_ctrl.make_face(
            req.exprname,
            req.intensity
        )

    def animation_request(self, req):
        self.robot_ctrl.play_animation(
            req.animation,
            req.fps
        )

    def animation_length(self, req):
        return self.robot_ctrl.animation_length(req)

    def __init__(self):
        rospy.init_node('head_ctrl')
        # Deprecated. WebUI should send direct commands
        self.pau_ctrl = PauCtrl()
        rospy.Subscriber("point_head", PointHead, self.pau_ctrl.point_head)

        # Robot Control
        self.robot_ctrl= SpecificRobotCtrl()
        rospy.Service("valid_face_exprs", ValidFaceExprs, self.valid_face_exprs)
        rospy.Subscriber("make_face_expr", MakeFaceExpr, self.face_request)
        # Animations
        rospy.Subscriber("play_animation", PlayAnimation, self.animation_request)
        rospy.Service("animation_length", AnimationLength, self.animation_length)

if __name__ == '__main__':
    HeadCtrl()
    rospy.loginfo("Started")
    rospy.spin()
