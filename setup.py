import os
from setuptools import setup, find_packages


def find_package_data(package, files=()):
    package_data = {}
    for dirpath, _, filenames in os.walk(package):
        for f in files:
            if f in filenames:
                package_path = dirpath.replace('/', '.')
                package_data.setdefault(package_path, []).append(f)
    return package_data


setup(name='loggingcontext',
      description='Logging Magic',
      version=0.3,
      author='Alex',
      author_email='alex@eat-up.org',
      packages=find_packages(),
      # package_data=find_package_data('loggingcontext',
      #                                # files=('proxies.txt',)
      #                                ),
      # entry_points={
      #   "console_scripts": [
      #       'lccon = loggingcontext.monitor:main',
      #   ]
      # },
      install_requires=[
        'pika',
        'pyyaml',
        'nose',
      ]
)
