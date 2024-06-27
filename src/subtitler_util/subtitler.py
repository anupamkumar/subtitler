import ffmpeg
import torch
import os
import whisper
import deep_translator
import argparse
import sys
import tempfile

from gooey import Gooey, GooeyParser
from datetime import datetime, timedelta

APP_DIR = os.path.dirname(__file__)
TEMP_DIR = tempfile.gettempdir()+"/subtitler"

def gen_lang_map():
    lang_map = {}
    if os.path.exists(APP_DIR+"/lang.tsv"):
        with open(APP_DIR+"/lang.tsv") as f:
            lang_data = f.readlines()
            for line in lang_data:
                temp = line.replace("\n","").split("\t")
                lang_name = temp[0].lower()
                iso_639_2 = temp[1].replace("/","_").replace("-","_").lower()
                iso_639_1 = temp[2].lower()
                if iso_639_1 == "":
                    lang_map[lang_name] = iso_639_2
                    lang_map[iso_639_2] = iso_639_2
                else:
                    lang_map[lang_name] = iso_639_1
                    lang_map[iso_639_1] = iso_639_1
        return lang_map
    else:
        raise Exception("file: 'lang.tsv' is missing. Please place it in the same directory as this script.")

LANG_MAP=gen_lang_map()
SUPPORTED_TRANSLATORS = [
    "google",
    "deepl",
    "yandex",
    "libre-translate",
    "microsoft",
    "chatgpt"
]
SUPPORTED_LANGS = [i.lower() for i in ["af","am","ar","as","az","ba","be","bg","bn","bo","br","bs","ca","cs","cy","da","de","el","en","es","et","eu","fa","fi","fo","fr","gl","gu","ha","haw","he","hi","hr","ht","hu","hy","id","is","it","ja","jw","ka","kk","km","kn","ko","la","lb","ln","lo","lt","lv","mg","mi","mk","ml","mn","mr","ms","mt","my","ne","nl","nn","no","oc","pa","pl","ps","pt","ro","ru","sa","sd","si","sk","sl","sn","so","sq","sr","su","sv","sw","ta","te","tg","th","tk","tl","tr","tt","uk","ur","uz","vi","yi","yo","yue","zh","Afrikaans","Albanian","Amharic","Arabic","Armenian","Assamese","Azerbaijani","Bashkir","Basque","Belarusian","Bengali","Bosnian","Breton","Bulgarian","Burmese","Cantonese","Castilian","Catalan","Chinese","Croatian","Czech","Danish","Dutch","English","Estonian","Faroese","Finnish","Flemish","French","Galician","Georgian","German","Greek","Gujarati","Haitian","Haitian Creole","Hausa","Hawaiian","Hebrew","Hindi","Hungarian","Icelandic","Indonesian","Italian","Japanese","Javanese","Kannada","Kazakh","Khmer","Korean","Lao","Latin","Latvian","Letzeburgesch","Lingala","Lithuanian","Luxembourgish","Macedonian","Malagasy","Malay","Malayalam","Maltese","Mandarin","Maori","Marathi","Moldavian","Moldovan","Mongolian","Myanmar","Nepali","Norwegian","Nynorsk","Occitan","Panjabi","Pashto","Persian","Polish","Portuguese","Punjabi","Pushto","Romanian","Russian","Sanskrit","Serbian","Shona","Sindhi","Sinhala","Sinhalese","Slovak","Slovenian","Somali","Spanish","Sundanese","Swahili","Swedish","Tagalog","Tajik","Tamil","Tatar","Telugu","Thai","Tibetan","Turkish","Turkmen","Ukrainian","Urdu","Uzbek","Valencian","Vietnamese","Welsh","Yiddish","Yoruba"]]


def gen_wav_file(vid_file: str, file_map: dict):
    output_audio_file = TEMP_DIR+"/"+( ".".join(vid_file.split("/")[-1].split(".")[:-1]) )+".wav"
    file_map[output_audio_file] = vid_file
    os.makedirs(TEMP_DIR,mode=0o777, exist_ok=True)
    input_stream = ffmpeg.input(vid_file)
    output_stream = ffmpeg.output(input_stream.audio,output_audio_file,acodec="pcm_s16le",ar="44100",ac="2")
    output_stream.run(overwrite_output=True, quiet=True)
    print(f"generated wav file for {vid_file} in {TEMP_DIR}")
    return output_audio_file

def cleanup():
    for f in os.listdir(TEMP_DIR):
        os.remove(TEMP_DIR+"/"+f)
    print("clean up done.")

def init_model():
    def load_model_pref():
        if os.path.exists(".model_pref"):
            with open(".model_pref") as f:
                return f.readline()
        else:
            return None
    def save_model_pref():
        with open(".model_pref","w") as f:
            f.write(model_size)
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    if load_model_pref() is not None:
        print(f"loading whisper's '{load_model_pref()}' model")
        return whisper.load_model(load_model_pref(),device=device)
    else:
        model_sizes = ["large-v3","large-v2","large","medium","small","base","tiny"]
        for model_size in model_sizes:
            try:
                model = whisper.load_model(model_size,device=device)
                print(f"model {model_size} loaded successfully.")
                save_model_pref()
                return model
            except torch.cuda.OutOfMemoryError:
                continue
            except Exception as e:
                print(f"failed to load model {model_size}")
                print(e)
        return None

def detect_lang(model: whisper.model, audio_file: str):
    audio = whisper.load_audio(audio_file)
    audio = whisper.pad_or_trim(audio)
    spectrogram = whisper.log_mel_spectrogram(audio).to(model.device)
    _, p = model.detect_language(spectrogram)
    return max(p, key=p.get)

def transcribe_audio(model: whisper.model, audio_file: str, language: str):
    
    def format_timestamp(time_in_seconds):
        dt_obj = datetime.strptime("00:00:00.000", '%H:%M:%S.%f')
        delta_seconds = timedelta(seconds=time_in_seconds)
        dt_obj += delta_seconds
        return dt_obj.strftime("%H:%M:%S,%f")[:-3]
    
    def post_process_result_for_srt(result):
        new_result = {}
        for seg in result["segments"]:
            seg_id = seg["id"] + 1
            new_result[seg_id] = {}
            new_result[seg_id]["start_time"] = format_timestamp(seg["start"])
            new_result[seg_id]["end_time"] = format_timestamp(seg["end"])
            new_result[seg_id]["text"] = seg["text"].strip()
        return new_result
    
    language = language.lower()
    if language not in SUPPORTED_LANGS:
        raise Exception("Cannot Transcribe! Unsupported Language. See Readme for list of supported languages.")
    audio= whisper.load_audio(audio_file)
    result = model.transcribe(audio,language=language,task="transcribe")
    return post_process_result_for_srt(result)

def translate_transcribed_result(transcribed_result, transcribed_language, target_language,translator="google", api_key=None):

    def init_translator(translator, transcribed_language, target_language, api_key):
        if translator not in SUPPORTED_TRANSLATORS:
            raise Exception("Unsupported Translator Service Provided. Please request translations from one of the the supported service providers. (see config for complete list.)")
        if translator == "google":
            translator = deep_translator.GoogleTranslator(source=transcribed_language, target=target_language)
        else:
            if api_key is None:
                raise Exception("API_KEY is necessary to access Deepl translation service. Please register for free and get an API-Key at https://www.deepl.com/en/your-account/keys.")
            if translator == "deepl":
                translator = deep_translator.DeeplTranslator(api_key=api_key, source=transcribed_language, target=target_language)
            elif translator == "yandex":
                translator = deep_translator.YandexTranslator(api_key=api_key, source=transcribed_language, target=target_language)
            elif translator == "microsoft":
                translator = deep_translator.MicrosoftTranslator(api_key=api_key, target=target_language)
            elif translator == "chatgpt":
                translator = deep_translator.ChatGptTranslator(api_key=api_key, target=target_language)
            elif translator == "libre-translate":
                translator = deep_translator.LibreTranslator(api_key=api_key, source=transcribed_language, target=target_language, base_url='https://libretranslate.com/')
        return translator

    translator = init_translator(translator, transcribed_language, target_language, api_key)
    translated_result = {}
    translation_cache = []
    for id, transcribed_obj in transcribed_result.items():
        translated_result[id] = {}
        translated_result[id]["start_time"] = transcribed_obj["start_time"]
        translated_result[id]["end_time"] = transcribed_obj["end_time"]
        translation_cache.append(transcribed_obj["text"])
    translated_results_cache = translator.translate_batch(translation_cache)
    for id, result_obj in translated_result.items():
        temp = translated_results_cache.pop(0) 
        if temp is not None:
            result_obj["text"] = temp
        else:
            result_obj["text"] = "."
    return translated_result

def save_result_as_srt(result: dict, target_language: str, video_file_name: str, default_srt_file: bool=False):

    def get_lang_iso_code(lang):
        return LANG_MAP[lang]
    
    target_language = target_language.lower()
    if default_srt_file:
        srt_file_name = ".".join(video_file_name.split(".")[:-1])+".default."+get_lang_iso_code(target_language)+".srt"
    else:
        srt_file_name = ".".join(video_file_name.split(".")[:-1])+"."+get_lang_iso_code(target_language)+".srt"
    with open(srt_file_name,"w") as f:
        for id, result_obj in result.items():
            f.write(str(id)+"\n")
            f.write(result_obj["start_time"]+" --> "+result_obj["end_time"]+"\n")
            f.write(result_obj["text"]+"\n\n")
    return srt_file_name

def check_if_file_is_video(file):
    try:
        probe_result = ffmpeg.probe(file)
        if "streams" in probe_result:
            for stream in probe_result["streams"]:
                if stream["codec_type"] == "video":
                    return True
        return False
    except:
        return False

def find_vid_files_in_dir(target_dir):
    files_list = []
    for cwd, dirs, files, in os.walk(target_dir):
        [files_list.append(cwd+"/"+afile) for afile in files if check_if_file_is_video(cwd+"/"+afile)]
    return files_list

def subtitle(vid_file_map: dict, audio_files: list, video_language: str, translation_languages: list, translation_service: str="google", translation_service_api_key: str = None, mode: str=None):

    def print_progress():
        if mode is None:
            print(f"progress: {current_step}/{total_steps}")
    
    total_steps = 2
    current_step = 1
    print_progress()
    model = init_model()
    current_step +=1
    print("Done.")
    total_steps += (len(audio_files)*2) + (len(audio_files)*len(translation_languages)*2)
    print_progress()
    for  audio_file in audio_files:
        print(f"transcribing video: {vid_file_map[audio_file]} in {video_language}")
        r=transcribe_audio(model, audio_file, video_language)
        current_step += 1
        print("Done.\nSaving...")
        print_progress()
        saved_file = save_result_as_srt(r,video_language,vid_file_map[audio_file],True)
        current_step += 1
        print(f"Done. Saved transcribed result as srt file: {saved_file}")
        print_progress()
        for translation_lang in translation_languages:
            print(f"translating subtitles to another language: {translation_lang}")
            r2=translate_transcribed_result(r,video_language,translation_lang,translator=translation_service, api_key=translation_service_api_key)
            current_step += 1
            print(f"Done.\nSaving...")
            print_progress()
            saved_file = save_result_as_srt(r2,translation_lang,vid_file_map[audio_file])
            current_step += 1
            print(f"Done. Saved translated result as srt file: {saved_file}")
            print_progress()
        

def process_args(args):
    vid_file_map= {}
    audio_files = []
    if args.video_files is None:
        for f in find_vid_files_in_dir(args.video_dir):
            audio_files.append(gen_wav_file(f,vid_file_map))
    elif args.video_dir is None:
        for f in [f for f in args.video_files if check_if_file_is_video(f)]:
            audio_files.append(gen_wav_file(f,vid_file_map))
    subtitle(vid_file_map,audio_files,args.video_language,args.translation_languages, translation_service=args.translation_service, translation_service_api_key=args.translation_service_api_key, mode=args.mode)
    cleanup()

def cli():
    parser = argparse.ArgumentParser(description="Transcribe and Translate subtitles for videos in any language.",prog="Subtitler")
    parser.add_argument("mode",help="enter mode as cli to run cli. not entering a mode will attempt to run the gui")
    ip_files_group = parser.add_mutually_exclusive_group(required=True)
    ip_files_group.add_argument("--video_files", help="full path to the video file you want to generate subtitles for",type=str, action='append')
    ip_files_group.add_argument("--video_dir", help="full path to directory where your video files may be",type=str)
    transcribe_group = parser.add_argument_group("Transcription Configuration")
    transcribe_group.add_argument("--video_language",help="Provide the language of the video(s). Set it to 'unknown' if you don't know and want AI to guess the language.(WARNING! This may be a bad-idea because the AI may make a mistake with language detection)",choices=SUPPORTED_LANGS, required=True)
    transcribe_group.add_argument("--force_language_autodetect",help="force language detection for all videos even if you provide 'video language' parameter", action="store_true")
    translation_group = parser.add_argument_group("Translation Configuration")
    translation_group.add_argument("--translation_languages",help="select all the languages you want to also translate the subtitles to.",choices=SUPPORTED_LANGS, nargs="*")
    translation_group.add_argument("--translation_service", help="pick a translation service.",choices=SUPPORTED_TRANSLATORS, default="google")
    translation_group.add_argument("--translation_service_api_key", help="not required for Google. But required for all other services.")
    args = parser.parse_args()

    if args.translation_languages is None:
        args.translation_languages = []
    
    print(f"Run Configuration: {args}\n")
    process_args(args)

@Gooey(clear_before_run=True,
       progress_regex=r"^progress: (?P<current>\d+)/(?P<total>\d+)$",
       hide_progress_msg=True,
       progress_expr="current / total * 100",
       show_time_remaining=True,
       hide_time_remaining_on_complete=False
       )
def gui():
    parser = GooeyParser(description="Transcribe and Translate subtitles for videos in any language.",prog="Subtitler")
    file_input_group = parser.add_argument_group("Input Configuration")
    ip_files_group = file_input_group.add_mutually_exclusive_group(required=True)
    ip_files_group.add_argument("--video_files", help="full path to the video file you want to generate subtitles for",widget='MultiFileChooser', nargs="+")
    ip_files_group.add_argument("--video_dir", help="full path to directory where your video files may be",widget='DirChooser')
    transcribe_group = parser.add_argument_group("Transcription Configuration")
    transcribe_group.add_argument("--video_language",help="Provide the language of the video(s). Set it to 'unknown' if you don't know and want AI to guess the language.(WARNING! This may be a bad-idea because the AI may make a mistake with language detection)",widget="FilterableDropdown",choices=SUPPORTED_LANGS, required=True)
    transcribe_group.add_argument("--force_language_autodetect",help="force language detection for all videos even if you provide 'video language' parameter", widget="BlockCheckbox", action="store_true")
    translation_group = parser.add_argument_group("Translation Configuration")
    translation_group.add_argument("--translation_languages",help="select all the languages you want to also translate the subtitles to.",widget="Listbox",choices=SUPPORTED_LANGS, nargs="*", gooey_options={'height':200})
    translation_group.add_argument("--translation_service", help="pick a translation service.",choices=SUPPORTED_TRANSLATORS, widget="Dropdown", default="google")
    translation_group.add_argument("--translation_service_api_key", help="not required for Google. But required for all other services.")
    args = parser.parse_args()
    if args.translation_languages is None:
        args.translation_languages = []
    args.mode = None
    print(f"Run Configuration: {args}\n")
    process_args(args)

def main():
    if 'cli' in sys.argv:
        cli()
    else:
        gui()

        
if __name__ == "__main__":
    main()