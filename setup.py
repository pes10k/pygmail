from setuptools import setup, find_packages # Always prefer setuptools over distutils
from codecs import open # To use a consistent encoding
from os import path
here = path.abspath(path.dirname(__file__))

description='Tools for interacting with GMail accounts over OAuth2, optionally in the tornado event loop'

setup(
    name='pygmail',
    version='0.7',
    packages=['pygmail'],
    description=description,
    author="Peter Snyder",
    author_email="psnyde2@uic.edu",
    license='MIT',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
    ],
    keywords='email development',
    install_requires=['imaplib2', 'google-api-python-client']
)
