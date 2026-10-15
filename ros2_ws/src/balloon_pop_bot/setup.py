from glob import glob
from setuptools import find_packages, setup

package_name = "balloon_pop_bot"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Eric",
    maintainer_email="eric@example.com",
    description="ROS2 wrapper for BalloonPopBot.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "balloon_pop_node = balloon_pop_bot.balloon_pop_ros2_node:main",
        ],
    },
)

