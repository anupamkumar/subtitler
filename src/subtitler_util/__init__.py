from datetime import datetime

__major_version__ = "1.0"
__build_date__ = None

try:
    with open("BUILD") as f:
        __build_date__ = f.readline()
except:
    pass

if __build_date__ is not None:
    VERSION = f"{__major_version__} build {__build_date__}"
else:
    VERSION = __major_version__