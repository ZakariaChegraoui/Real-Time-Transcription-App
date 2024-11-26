import nest_asyncio
nest_asyncio.apply()

import sounddevice as sd
import asyncio
import websockets
import numpy as np
import json
from collections import deque
import time
import pyautogui

DEEPGRAM_API_KEY = 'adef3dc89ea071c707b3f2994e10a7e71381b3ae'
CHANNELS = 1
RATE = 16000
BLOCKSIZE = 8000

# Significantly adjusted parameters for longer sentences
SILENCE_THRESHOLD = 0.1    # Sensitivity to silence
SILENCE_DURATION = 1000     # Longer pause needed to end sentence (2.5 seconds)
MIN_SENTENCE_DURATION = 2.0  # Minimum sentence length
MAX_BUFFER_DURATION = 60.0   # Allow for very long sentences (30 seconds)
NOISE_FRAMES = 10           # Number of frames to check for consistent silence

class AudioProcessor:
    """
    Processes audio data for silence detection and transcription.
    """
    def __init__(self, silence_threshold, silence_duration, min_sentence_duration, max_buffer_duration, noise_frames):
        self.silence_threshold = silence_threshold  # Sensitivity to silence
        self.silence_duration = silence_duration    # Duration of silence to detect end of sentence
        self.min_sentence_duration = min_sentence_duration  # Minimum duration for a valid sentence
        self.max_buffer_duration = max_buffer_duration  # Maximum buffer duration before sending data
        self.noise_frames = noise_frames  # Number of frames used for noise/silence detection

        # State management
        self.audio_buffer = deque()
        self.is_speaking = False
        self.silence_start = None
        self.sentence_start = None
        self.last_send_time = time.time()
        self.websocket = None
        self.buffer_samples = 0
        self.voice_detected = False
        self.silent_frame_count = 0
        self.last_rms_values = deque(maxlen=noise_frames)

    def set_websocket(self, ws):
        """
        Set the WebSocket for sending audio data.
        """
        self.websocket = ws

    def is_silent(self, audio_data):
        """
        Determine if the current audio frame is silent based on RMS.
        """
        rms = np.sqrt(np.mean(np.square(audio_data)))  # Calculate RMS
        self.last_rms_values.append(rms)

        # Only consider silence if enough consecutive quiet frames
        if len(self.last_rms_values) == self.noise_frames:
            avg_rms = np.mean(self.last_rms_values)
            return avg_rms < self.silence_threshold
        return False

    async def process_audio_chunk(self, audio_data):
        """
        Process each audio chunk to detect speech or silence.
        """
        current_time = time.time()
        self.audio_buffer.append(audio_data)
        self.buffer_samples += len(audio_data)

        is_current_silent = self.is_silent(audio_data)

        # If the buffer exceeds the maximum duration, send the audio
        buffer_duration = self.buffer_samples / RATE
        if buffer_duration >= self.max_buffer_duration:
            if self.voice_detected:
                print("\nReached maximum buffer duration - processing long sentence")
                await self.send_buffer()
            else:
                self.clear_buffer()
            return

        # Handle voice activity and silence detection
        if not is_current_silent:
            # Voice detected
            self.voice_detected = True
            self.silent_frame_count = 0
            self.silence_start = None
            if not self.sentence_start:
                self.sentence_start = current_time
        else:
            # Silence detected
            if self.voice_detected:
                self.silent_frame_count += 1
                if self.silence_start is None:
                    self.silence_start = current_time

                silence_duration = current_time - self.silence_start
                if silence_duration >= self.silence_duration:
                    # End of sentence
                    if (self.sentence_start and 
                        current_time - self.sentence_start >= self.min_sentence_duration):
                        print("\nDetected end of sentence")
                        await self.send_buffer()
                        self.reset_state()

        # Send partial data for very long sentences
        if current_time - self.last_send_time >= 8.0 and self.voice_detected:
            print("\nSending partial long sentence")
            await self.send_buffer()

    async def send_buffer(self):
        """
        Send buffered audio to the WebSocket.
        """
        if self.websocket and len(self.audio_buffer) > 0:
            try:
                combined_audio = np.concatenate(list(self.audio_buffer))
                audio_data = (combined_audio * 32767).astype(np.int16)  # Convert to 16-bit PCM
                await self.websocket.send(audio_data.tobytes())
                self.last_send_time = time.time()
                self.clear_buffer()
            except Exception as e:
                print(f"Error sending audio: {e}")

    def clear_buffer(self):
        """
        Clear the audio buffer.
        """
        self.audio_buffer.clear()
        self.buffer_samples = 0

    def reset_state(self):
        """
        Reset state variables after processing a sentence.
        """
        self.voice_detected = False
        self.silent_frame_count = 0
        self.sentence_start = None
        self.last_rms_values.clear()


async def stream_microphone(loop,callback = None,constants = None,stop_event = None):
    
    while not stop_event.is_set():
        
        try:
            mic_device_index = constants.get("mic_device")
            api_key = constants.get("api_key")
            language = constants.get("language")
            print(api_key ,mic_device_index,language)
            async with websockets.connect(
                'wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate=16000&channels=1&model=nova-2&language='+language,
                extra_headers={'Authorization': f'Token {api_key}'}
            ) as ws:
                print('connected')
                audio_processor = AudioProcessor(
                    silence_threshold=constants["silence_threshold"],
                    silence_duration=constants["silence_duration"],
                    min_sentence_duration=constants["min_sentence_duration"],
                    max_buffer_duration=constants["max_buffer_duration"],
                    noise_frames=constants["noise_frames"]
                )
                audio_processor.set_websocket(ws)
                
                def audio_callback(indata, frames, time_info, status):
                    if status:
                        print(status)
                    if stop_event.is_set():
                        raise sd.CallbackAbort
                    try:
                        asyncio.run_coroutine_threadsafe(
                            audio_processor.process_audio_chunk(indata.copy()), 
                            loop
                        )
                    except Exception as e:
                        print(f"Error in audio callback: {e}")

                with sd.InputStream(
                    device=mic_device_index,
                    channels=CHANNELS,
                    samplerate=RATE,
                    blocksize=BLOCKSIZE,
                    callback=audio_callback
                ):
                    print("\nStreaming from microphone...")
                    print("Speak naturally - the system will wait for longer pauses between sentences")
                    print("Press Ctrl+C to stop")
                    
                    try:
                        async for msg in ws:
                            if stop_event.is_set():
                                break
                            msg = json.loads(msg)
                            transcript = msg['channel']['alternatives'][0]['transcript']
                            if transcript:
                                print(f"\nTranscript: {transcript}")
                                #clipboard.copy(transcript)
                                pyautogui.typewrite(transcript)
                                if callback:
                                    callback(transcript)
                     
                    except websockets.exceptions.ConnectionClosed:
                        if stop_event.is_set():
                                break
                        print("\nConnection closed. Reconnecting...")
                        
                        continue
                    except Exception as e:
                        if stop_event.is_set():
                                break
                        print(f"Error in websocket handling: {e}")
                        continue

        except Exception as e:
            if stop_event.is_set():
                break
            print(f"Connection error: {e}")
            print("Retrying in 2 seconds...")
            error_message = "Connection closed. Reconnecting... Check your api key or your connection\nRetrying in 2 seconds...\n"
            callback(error_message,True)
            await asyncio.sleep(2)

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(stream_microphone(loop))
    except KeyboardInterrupt:
        print("\nProgram stopped by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        loop.close()