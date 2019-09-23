from setuptools import setup
import re

requirements = []

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

version = ''
with open('discord/__init__.py') as f:
    version = re.search(
        r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', f.read(), re.MULTILINE).group(1)

readme = ""

with open("README.md") as f:
    readme = f.read()

setup(name="chatango.py",
      author="Yado",
      url="https://github.com/neokuze/chatango-lib",
      version=version,
      packages=["chatango"],
      license="MIT",
      description="A Python library for connecting to Chatango",
      long_description=readme,
      long_description_content_type="text/markdown",
      install_requires=requirements,
      python_requires=">=3.6"
      )
