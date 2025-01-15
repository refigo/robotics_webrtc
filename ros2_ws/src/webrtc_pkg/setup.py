from setuptools import find_packages, setup

from glob import glob
import os

package_name = 'webrtc_pkg'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        
        # Copy Static files to use after building
        ('lib/python3.10/site-packages/' + package_name, [
            os.path.join(package_name, 'index.html'),
            os.path.join(package_name, 'client.js'),
            os.path.join(package_name, 'placeholder.jpg'),
        ]),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='refi',
    maintainer_email='refi@xyzcorp.io',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            "streaming_node = webrtc_pkg.streaming_node:main"
        ],
    },
)
