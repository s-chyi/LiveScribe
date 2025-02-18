import os    
import re    
import json  
import time  
import asyncio    
  
from dotenv import load_dotenv  
from logs import logger  
from re import finditer    
from datetime import timedelta, datetime    
from threading import Thread, Event, Lock    
  
import azure.cognitiveservices.speech as speechsdk    
from azure.ai.translation.text import TextTranslationClient    
from azure.core.exceptions import HttpResponseError    
from azure.core.credentials import AzureKeyCredential    
from google.cloud import translate    
  
import deepl    
  
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO    
from cachetools import TTLCache    
  
RECOGNIZER = "Azure"
# 翻譯器的類型，可以是 "Azure"、"DeepL" 或 "Google"  
TRANSLATOR = "Google"  # "Azure", "DeepL", "Google"    

# 音訊檔案名稱，若為 None 則使用默認麥克風  
FILE_NAME = None    
# FILE_NAME = r"data\test.wav"
  
# 載入環境變數  
load_dotenv()  

# Google Cloud 項目 ID 和路徑  
PROJECT_ID = os.getenv('GOOGLE_PROJECT')
PARENT = f"projects/{PROJECT_ID}/locations/global"    
# 設定 Google Cloud 認證檔案的路徑  
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials/google_credentials.json"    
  
# 自訂詞彙列表，供語音識別器使用以提高識別準確性  
custom_phrases = ["AI", "Machine Learning", "Nick"]
  
# 從環境變數中取得 Azure 語音識別的金鑰和區域  
speech_key = os.getenv('SPEECH_KEY')    
service_region = os.getenv('SPEECH_REGION')    

  
app = Flask(__name__)    
app.config['SECRET_KEY'] = 'secret!'    
# 初始化 SocketIO，允許所有的跨域請求，使用 threading 模式  
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')  # 使用 threading 模式    
  
class TranslationCache:    
    """    
    使用 cachetools 的 TTLCache 實現快取，提高效能    
    """    
    def __init__(self, max_size=1000, expire_time=300):    
        self.cache = TTLCache(maxsize=max_size, ttl=expire_time)    
  
    def get(self, key):    
        return self.cache.get(key)    
  
    def set(self, key, value):    
        self.cache[key] = value    
  
class TranslationManager:    
    """    
    翻譯管理器，負責管理翻譯請求、快取以及故障轉移機制    
    """    
    def __init__(self, max_workers=4, cache_size=1000):    
        self.semaphore = asyncio.Semaphore(max_workers)    
        self.cache = TranslationCache(max_size=cache_size)    
        self.error_counts = {}    
        self.error_threshold = 3    
        self.fallback_order = {
            "Azure": ["Google", "DeepL"],    
            "Google": ["Azure", "DeepL"],    
            "DeepL": ["Azure", "Google"]    
        }    
        self.translation_lock = Lock()    
        self.stop_flag = False    
  
    async def translate_with_fallback(self, translator_func, text, source_lang, target_lang):    
        """    
        使用翻譯函數進行翻譯，並在發生錯誤時嘗試故障轉移    
        """    
        async with self.semaphore:    
            try:    
                if self.stop_flag:    
                    return None    
                return await translator_func(text, source_lang, target_lang)    
            except Exception as e:    
                if not self.stop_flag:    
                    logger.error(f"Translation error with {translator_func.__name__}: {e}")    
                return None    
  
class ContinuousTranslation:    
    """    
    持續翻譯服務類    
    負責語音識別、翻譯處理和信號傳送    
    """    
    def __init__(self, socketio):    
        self.socketio = socketio    
        self.stop_flag = False    
        self.current_transcriber = RECOGNIZER    
        self.current_translator = TRANSLATOR    
  
        # 初始化翻譯管理器    
        self.translation_manager = TranslationManager(    
            max_workers=4,    
            cache_size=1000    
        )    
  
        # 初始化狀態變數    
        self.last_text = {"ch": "", "en": ""}    
        self.current_language = "en-US"  # 默認為英語    
  
        # 臨時數據    
        self.previous_text = {"mix": ""}    
        self.previous_completed = {"mix": "", "prev_prev": ""}    
  
        # 完整文本記錄    
        self.full_text = {"en": "", "ch": ""}    
  
        # 文件路徑設定    
        timestamp = datetime.now().strftime('%Y%m%d')    
        self.file_paths = {    
            "log": f"logs/{timestamp}_log.txt",    
            "text": f"logs/{timestamp}_texts.txt",    
            "translation": f"logs/{timestamp}_translations.txt"    
        }    
  
        # 初始化翻譯服務    
        self._setup_translation_service()    
  
    def _setup_translation_service(self):    
        """設定翻譯服務"""    
        try:    
            self.translators = {    
                "DeepL": self._translate_with_deepl,
                "Azure": self._translate_with_azure,
                "Google": self._translate_with_google
            }    
  
            # 設定 DeepL 翻譯器    
            self.DeepL_translator = deepl.Translator(    
                auth_key=os.getenv('DEEPL_KEY')    
            )
  
            # 設定 Azure 翻譯服務  
            self.azure_credential = AzureKeyCredential(os.getenv('AZURE_TRANSLATOR_KEY'))    
            self.azure_translator = TextTranslationClient(
                region=os.getenv('AZURE_TRANSLATOR_REGION'),
                credential=self.azure_credential
            )
  
            self.google_translator = translate.TranslationServiceClient()    
  
        except Exception as e:    
            logger.error(f"Translation service setup error: {e}")    
            raise    
  
    async def translation_continuous(self):    
        """    
        持續進行語音識別與翻譯的主循環    
        """    
        self.loop = asyncio.get_running_loop()  # 獲取當前運行的事件循環    
        recognizer = self._init_recognizer()    

        self._add_custom_phrases(recognizer)    
  
        done_event = asyncio.Event()    
  
        self._connect_recognizer_events(recognizer, done_event)    

        recognizer.start_continuous_recognition_async()    
  
        await done_event.wait()    
  
    def _init_recognizer(self):    
        """初始化語音識別器"""    
        try:    
            speech_config = self._create_speech_config()    
            audio_config = self._create_audio_config()    
            language_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(    
                languages=["en-US", "zh-TW"]    
            )    

            return speechsdk.SpeechRecognizer(    
                speech_config=speech_config,    
                audio_config=audio_config,    
                auto_detect_source_language_config=language_config    
            )    
  
        except Exception as e:    
            logger.error(f"Recognizer initialization error: {e}")    
            raise    
  
    def _create_speech_config(self):    
        """創建語音配置"""    
        if self.current_transcriber == "Azure":    
            config = speechsdk.SpeechConfig(    
                subscription=speech_key,    
                region=service_region    
            ) 
        else:    
            raise ValueError("Invalid recognizer type")    
        timestamp = datetime.now().strftime('%Y%m%d')  
  
        config.speech_recognition_language = "en-US"    
        config.enable_dictation()    
        config.set_property(    
            speechsdk.PropertyId.Speech_LogFilename,    
            f"logs/{timestamp}_speech_log.txt"    
        )    
        config.set_property(    
            speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption,    
            'TrueText'    
        )    
        config.set_profanity(speechsdk.ProfanityOption.Raw)    
        config.set_property(    
            speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode,    
            'Continuous'    
        )    
        return config    
  
    def _create_audio_config(self):    
        """創建音訊配置"""    
        return (speechsdk.audio.AudioConfig(filename=FILE_NAME)
                if FILE_NAME    
                else speechsdk.audio.AudioConfig(use_default_microphone=True))    
  
    def _add_custom_phrases(self, recognizer):    
        """添加自訂詞彙"""    
        try:    
            phrase_list = speechsdk.PhraseListGrammar.from_recognizer(recognizer)    
            for phrase in custom_phrases:    
                phrase_list.addPhrase(phrase)    
        except Exception as e:    
            logger.error(f"Add custom phrases error: {e}")    
  
    def _connect_recognizer_events(self, recognizer, done_event):    
        """連接識別器事件"""    
        recognizer.session_started.connect(    
            lambda evt: logger.info(f'Session started: {evt}')    
        )    
        recognizer.session_stopped.connect(    
            lambda evt: self._handle_recognition_stop(evt, done_event)    
        )    
        recognizer.canceled.connect(    
            lambda evt: self._handle_recognition_stop(evt, done_event)    
        )    
        recognizer.recognizing.connect(self._handle_recognizing)    
        recognizer.recognized.connect(self._handle_recognized)    
  
    def _handle_recognition_stop(self, evt, done_event):    
        """處理識別停止事件"""    
        logger.info(f"Recognition stopped: {evt}")    
        self.loop.call_soon_threadsafe(done_event.set)   
  
    def _handle_recognizing(self, evt):    
        """處理識別中事件"""    
        try: 
            if self.stop_flag:    
                return    
            if evt.result.reason == speechsdk.ResultReason.RecognizingSpeech:    
  
                text = evt.result.text
                if self.current_transcriber == "Azure":    
                    language = json.loads(evt.result.json)["PrimaryLanguage"]["Language"]    
                else:    
                    language = "en-US"    
  
                # 執行翻譯    
                future = asyncio.run_coroutine_threadsafe(    
                    self._translate_text(text, language),    
                    self.loop    
                )    
                ch_text, en_text = future.result()    
  
                display_text = ch_text if language == "en-US" else en_text    
  
                current_text, prev_text = self.format_mixed_text(display_text)  
                display_text = prev_text + "<br>" + current_text if prev_text else current_text    
                self.socketio.emit('update_text', {'text': display_text, 'lang': language})    
  
                # 保存當前語言信息    
                self.current_language = language    
  
        except Exception as e:    
            if not self.stop_flag:    
                logger.error(f"Recognizing handler error: {e}")    
  
    def _handle_recognized(self, evt):    
        """處理識別完成事件"""    
        try:    
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:    
                # 獲取時間和文本信息    
                start_time = evt.result.offset / 10**7    
                end_time = (evt.result.offset + evt.result.duration) / 10**7    
                text = evt.result.text
                if self.current_transcriber == "Azure":    
                    language = json.loads(evt.result.json)["PrimaryLanguage"]["Language"]    
                else:    
                    language = "en-US"    
  
                # 執行翻譯    
                future = asyncio.run_coroutine_threadsafe(    
                    self._translate_text(text, language),    
                    self.loop    
                )    
                ch_text, en_text = future.result()    
  
                # 更新完成的文本    
                self.previous_completed["prev_prev"] = self.previous_completed["mix"]
                if language == "en-US":
                    self.previous_completed["mix"] = ch_text
                    text = en_text
                else:
                    self.previous_completed["mix"] = en_text    
                    text = ch_text
  
                # 更新完整文本    
                self._update_full_text(ch_text, en_text)    
  
                # 寫入文件    
                self._write_to_files(start_time, end_time, text, self.previous_completed["mix"])    
  
        except Exception as e:    
            logger.error(f"Recognition handler error: {e}")    
  
    async def _translate_text(self, text, language):    
        """    
        優化的翻譯實現，包含快取、錯誤處理和故障轉移機制    
        """    
        try:    
            if not text or not text.strip():    
                return "", ""    
  
            cache_key = f"{text}_{language}_{self.current_translator}"    
  
            cached_result = self.translation_manager.cache.get(cache_key)    
            if cached_result:    
                return cached_result    
  
            source_lang, target_lang = self._switch_language_code(language)    
  
            # 獲取當前翻譯器    
            current_translator = self.current_translator    
            translator_func = self.translators[current_translator]    
  
            # 嘗試主要翻譯器    
            result = await self.translation_manager.translate_with_fallback(    
                translator_func, text, source_lang, target_lang    
            )    
  
            # 如果主要翻譯失敗，嘗試故障轉移    
            if result is None:    
                with self.translation_manager.translation_lock:    
                    self.translation_manager.error_counts[current_translator] = self.translation_manager.error_counts.get(current_translator, 0) + 1    
  
                    if self.translation_manager.error_counts[current_translator] >= self.translation_manager.error_threshold:    
  
                        for fallback_translator in self.translation_manager.fallback_order[current_translator]:    
                            translator_func = self.translators[fallback_translator]    
                            result = await self.translation_manager.translate_with_fallback(    
                                translator_func, text, source_lang, target_lang    
                            )    
                            if result:    
                                logger.info(f"Fallback to {fallback_translator} successful")    
                                break    
  
            if not result:    
                logger.error("All translation attempts failed")    
                return "", ""    
  
            if language == "en-US":    
                final_result = (result, text)    
            else:    
                final_result = (text, result)    
  
            # 更新快取    
            self.translation_manager.cache.set(cache_key, final_result)    
  
            # 重置成功翻譯器的錯誤計數    
            with self.translation_manager.translation_lock:    
                self.translation_manager.error_counts[self.current_translator] = 0    
  
            return final_result    
  
        except Exception as e:    
            logger.error(f"Translation error: {str(e)}")    
            return "", ""    
  
    def _switch_language_code(self, language):    
        """    
        根據語言代碼設定源語言和目標語言    
        """    
        if language == "en-US":    
            if self.current_translator == "DeepL":    
                source_lang = "EN"    
                target_lang = "ZH"    
            elif self.current_translator in ["Azure"]:    
                source_lang = "en"    
                target_lang = "zh-Hans"    
            elif self.current_translator == "Google":    
                source_lang = "en"    
                target_lang = "zh-TW"    
        elif language == "zh-TW":    
            if self.current_translator == "DeepL":    
                source_lang = "ZH"    
                target_lang = "EN-US"    
            elif self.current_translator in ["Azure"]:
                source_lang = "zh-Hans"
                target_lang = "en"
            elif self.current_translator == "Google":
                source_lang = "zh-TW"
                target_lang = "en-US"
        else:    
            # 默認為英語到中文    
            source_lang = "en"    
            target_lang = "zh-Hans"    
        return source_lang, target_lang    
  
    async def _translate_with_deepl(self, text, source_lang, target_lang):    
        """使用 DeepL 進行翻譯"""    
        try:    
            config = {
                "text": text,    
                "source_lang": source_lang,    
                "target_lang": target_lang,
                "model_type": "prefer_quality_optimized"
            }
            
            response = await asyncio.get_event_loop().run_in_executor(    
                None,    
                lambda: self.DeepL_translator.translate_text(    
                    **config
                )    
            )    
            return response.text    
        except Exception as e:    
            logger.error(f"DeepL translation error: {e}")    
            return ""    
  
    async def _translate_with_azure(self, text, source_lang, target_lang):    
        """使用 Azure 翻譯服務進行翻譯"""    
        try:    
            from_language = source_lang
            to_language = [target_lang]
            input_text_elements = [text] 
            response = await asyncio.get_event_loop().run_in_executor(    
                None,    
                lambda: self.azure_translator.translate(    
                    body=input_text_elements,    
                    to_language=to_language,    
                    from_language=from_language    
                )    
            )    
            translation = response[0] if response else None    
  
            if translation:    
                return translation.translations[0].text    
            return ""    
        except HttpResponseError as exception:    
            if exception.error is not None:    
                logger.error(f"Error Code: {exception.error.code}")    
                logger.error(f"Message: {exception.error.message}")    
            return ""    
  
    async def _translate_with_google(self, text, source_lang, target_lang):    
        """使用 Google 翻譯進行翻譯"""    
        try:  
            
            config = {    
                    "parent": PARENT,    
                    "contents": [text],    
                    "mime_type": "text/plain", 
                    "source_language_code": source_lang,    
                    "target_language_code": target_lang
                } 
            response = await asyncio.get_event_loop().run_in_executor(    
                None,    
                lambda: self.google_translator.translate_text(    
                    request=config
                )    
            )    
            if response.translations:    
                return response.translations[0].translated_text    
            return ""    
        except Exception as e:    
            logger.error(f"Google translation error: {e}")    
            return ""    
  
    def _update_full_text(self, ch_text, en_text):    
        """更新完整文本"""    
        self.full_text["ch"] += ch_text    
        self.full_text["en"] += en_text    
  
        # 限制文本長度    
        max_length = 19 * 12    
        self.full_text["ch"] = self.full_text["ch"][-max_length:]    
        self.full_text["en"] = self.full_text["en"][-max_length:]    
  
        self.previous_completed["mix"] = self.previous_completed["mix"][-max_length:]    
  
    def format_mixed_text(self, current_text: str) -> tuple:  
        MAX_SENTENCES_PER_PARAGRAPH = 4  

        def split_into_sentences(text):
            sentences = re.split(r'(?<=[.!?。！？])\s*', text)
            sentences = [s for s in sentences if s.strip()]  
            return sentences  
        
        def join_sentences(sentences):  
            return ''.join(sentences)  

        prev_prev_sentences = []   
        prev_sentences = []  

        current_sentences = split_into_sentences(current_text)  

        prev_text = self.previous_completed.get("mix", "")
        prev_text_sentences = split_into_sentences(prev_text)  
        prev_prev_text = self.previous_completed.get("prev_prev", "")
        prev_prev_text_sentences = split_into_sentences(prev_prev_text)  

        if len(current_sentences) > MAX_SENTENCES_PER_PARAGRAPH:  
            sentences_to_move = current_sentences[:MAX_SENTENCES_PER_PARAGRAPH]  
            current_sentences = current_sentences[MAX_SENTENCES_PER_PARAGRAPH:]  
            prev_sentences.extend(sentences_to_move)  
    
            if len(prev_sentences) > MAX_SENTENCES_PER_PARAGRAPH:  
                num_extra = len(prev_sentences) - MAX_SENTENCES_PER_PARAGRAPH  
                extra_sentences = prev_sentences[:num_extra]  
                prev_sentences = prev_sentences[num_extra:]  
    
                prev_prev_sentences.extend(extra_sentences)  
    
                if len(prev_prev_sentences) > MAX_SENTENCES_PER_PARAGRAPH:  
                    prev_prev_sentences = prev_prev_sentences[-MAX_SENTENCES_PER_PARAGRAPH:]  
            else:
                prev_prev_sentences = prev_text_sentences
        else:  
            prev_sentences = prev_text_sentences
            prev_prev_sentences = prev_prev_text_sentences

    
        combined_prev_text = '<br>'.join(filter(None, [  
            join_sentences(prev_prev_sentences[-MAX_SENTENCES_PER_PARAGRAPH:]),  
            join_sentences(prev_sentences[-MAX_SENTENCES_PER_PARAGRAPH:])  
        ]))  
    
        current_paragraph = join_sentences(current_sentences)  
    
        return current_paragraph, combined_prev_text  
  
    def _write_to_files(self, start_time, end_time, text, translate_text):    
        """寫入文件"""    
        try:    
            timestamp = self._format_time(start_time)    
            end_timestamp = self._format_time(end_time)    
  
            # 寫入原文    
            self._write_to_file(    
                self.file_paths["text"],    
                f"{timestamp}-{end_timestamp} {text}\n"    
            )    
  
            # 寫入翻譯    
            self._write_to_file(    
                self.file_paths["translation"],    
                f"{timestamp}-{end_timestamp} {translate_text}\n"    
            )    
  
        except Exception as e:    
            logger.error(f"File writing error: {e}")    
  
    @staticmethod    
    def _format_time(seconds):    
        """格式化時間"""    
        delta = timedelta(seconds=seconds)    
        formatted = str(delta).split('.')[0]    
        return formatted[2:] if formatted.startswith("0:") else formatted    
  
    def _write_to_file(self, file_path, content):    
        """寫入文件的輔助方法"""    
        with open(file_path, 'a', encoding='utf-8') as f:    
            f.write(content)    
  
    def cleanup(self):    
        """清理資源"""    
        try:    
            self.stop_flag = True    
            self.translation_manager.stop_flag = True    
            logger.info("Translation service cleaned up successfully")    
        except Exception as e:    
            logger.error(f"Translation service cleanup error: {e}")    
  
@app.route('/')    
def index():    
    """渲染主頁面"""    
    return render_template('index.html')    
  
@socketio.on('connect')
def handle_connect():
    client_ip = request.remote_addr
    logger.info(f"Client connected: {request.sid}, IP: {client_ip}")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Client disconnected: {request.remote_addr}")
  
def start_translation_service(service):    
    """啟動翻譯服務"""    
    asyncio.run(service.translation_continuous())    
  
if __name__ == '__main__':    
    service = ContinuousTranslation(socketio)    
    recognition_thread = Thread(target=start_translation_service, args=(service,), daemon=True)    
    recognition_thread.start()
    try:
        socketio.run(app, host='0.0.0.0', port=5015)
    except KeyboardInterrupt:
        logger.info("Exiting...")
    finally:
        service.cleanup()