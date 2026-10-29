from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="contract-note-parser",
    version="2.0.0",
    author="Arihant Begani",
    description="Python API library for parsing Indian stock market Equity Contract Notes with broker template system.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/arihant-begani/file_parser",
    packages=find_packages(),
    py_modules=["contract_note_parser", "broker_templates", "app"],
    install_requires=[
        "pdfplumber>=0.10.0",
        "reportlab>=4.0.0",
    ],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Financial and Insurance Industry",
        "Intended Audience :: Developers",
        "Topic :: Office/Business :: Financial :: Investment",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "contract-note-parser=contract_note_parser:main",
        ],
    },
)
