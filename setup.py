from setuptools import setup, find_packages

setup(
    name="bibox",
    version="0.1.1",
    description="A stateless CLI literature manager",
    author="Bibox Contributors",
    license="MIT",
    packages=find_packages(),
    include_package_data=True,
    package_data={"bibox": ["help_content.json"]},
    entry_points={
        "console_scripts": [
            "bibox=bibox.cli:main",
        ],
    },
    install_requires=[
        "pymupdf>=1.23.0",
        "requests>=2.25.0",
        "rich>=13.0.0",
        "argcomplete>=3.0.0"
    ],
)