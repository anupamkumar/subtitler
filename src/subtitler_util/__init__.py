import os
import tempfile

__major_version__ = "1.0"
__build_date__ = None

if os.name == 'nt':
    DIR_DELIM = "\\"
else:
    DIR_DELIM = "/"

APP_DIR = os.path.dirname(__file__)
TEMP_DIR = tempfile.gettempdir()+DIR_DELIM+"subtitler"

try:
    with open(APP_DIR+DIR_DELIM+"BUILD") as f:
        __build_date__ = f.readline()
except:
    pass

if __build_date__ is not None:
    VERSION = f"{__major_version__}.{__build_date__}"
else:
    VERSION = __major_version__