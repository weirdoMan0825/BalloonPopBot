from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "model_path",
            default_value="best_float16.tflite",
            description="TFLite model path.",
        ),
        DeclareLaunchArgument(
            "serial_port",
            default_value="/dev/ttyUSB0",
            description="Arduino serial device.",
        ),
        DeclareLaunchArgument(
            "camera_id",
            default_value="0",
            description="USB camera index.",
        ),
        DeclareLaunchArgument(
            "conf_thres",
            default_value="0.70",
            description="YOLO confidence threshold.",
        ),
        DeclareLaunchArgument(
            "startup_sequence",
            default_value="true",
            description="Run original warmup + short forward sequence before tracking.",
        ),
        Node(
            package="balloon_pop_bot",
            executable="balloon_pop_node",
            name="balloon_pop_node",
            output="screen",
            parameters=[{
                "model_path": LaunchConfiguration("model_path"),
                "serial_port": LaunchConfiguration("serial_port"),
                "camera_id": LaunchConfiguration("camera_id"),
                "conf_thres": LaunchConfiguration("conf_thres"),
                "startup_sequence": LaunchConfiguration("startup_sequence"),
            }],
        ),
    ])

