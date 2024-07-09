import os
import tempfile
import sys

__major_version__ = "1.0"
__build_date__ = None

if os.name =='nt':
    DIR_DELIM = "\\"
    scripts_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
    if not os.path.exists(scripts_dir+DIR_DELIM+"subtitler"):
        import shutil
        shutil.copy(scripts_dir+DIR_DELIM+"subtitler.exe",scripts_dir+DIR_DELIM+"subtitler")
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