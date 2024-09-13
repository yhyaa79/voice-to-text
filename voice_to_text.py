'''
tiny	39 M	tiny.en	tiny	~1 GB	~32x
base	74 M	base.en	base	~1 GB	~16x
small	244 M	small.en	small	~2 GB	~6x
medium	769 M	medium.en	medium	~5 GB	~2x
large	1550 M	N/A	large	~10 GB	1x
'''



import telebot
from telebot.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
import whisper
import os
from g4f.client import Client
import threading
import queue

# Load the Whisper model
model = whisper.load_model("large")

# Initialize the bot with your bot token
API_TOKEN = "7419737791:AAElCmpsL3R3sJcuWCjjStiCoFZ-vq5wPug"
bot = telebot.TeleBot(API_TOKEN)

# Dictionary to store transcriptions with unique user IDs
user_transcriptions = {}

# Queue for handling more than 5 concurrent requests
request_queue = queue.Queue()

# Semaphore to limit concurrent requests to 5
sem = threading.Semaphore(5)

def chat_with_gpt(text_chatGPT_35_turbo):
    try:
        system_message = {
            "role": "system",
            "content": "You are an assistant that corrects input sentences while preserving the original language. Your task is to correct any mistakes in the input sentence and return only the corrected version. Do not change the language or add any extra information."
        }
        user_message = {"role": "user", "content": text_chatGPT_35_turbo}

        client = Client()
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[system_message, user_message],
            temperature=0.5,
            max_tokens=50,
            top_p=0.9,
            frequency_penalty=0.5,
            presence_penalty=0.6
        )

        model_reply = response.choices[0].message.content
        return model_reply
    except Exception as e:
        print(f"An error occurred: {e}")
        return "Unfortunately an error has occurred, please try again."

def process_request(message: Message):
    try:
        # Wait for an available slot (up to 5 concurrent requests)
        sem.acquire()

        # Send "Please wait..." message
        wait_message = bot.reply_to(message, "Please wait...")

        # Download the file
        file_info = bot.get_file(message.voice.file_id if message.content_type == 'voice' else message.audio.file_id)
        file_path = file_info.file_path
        downloaded_file = bot.download_file(file_path)
        
        # Save the file temporarily
        with open("temp_voice_file.ogg", 'wb') as new_file:
            new_file.write(downloaded_file)

        # Transcribe the audio using the Whisper model
        result = model.transcribe("temp_voice_file.ogg")
        transcription = result["text"]

        # Clean up the temporary file
        os.remove("temp_voice_file.ogg")

        # Store transcription in dictionary for the user
        user_transcriptions[message.from_user.id] = transcription

        # Delete the "Please wait..." message
        bot.delete_message(message.chat.id, wait_message.message_id)

        # Create reply keyboard with Correction and Reset options
        markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        correction_btn = KeyboardButton("Correction")
        reset_btn = KeyboardButton("Reset")
        markup.add(correction_btn, reset_btn)
        
        # Send transcription with keyboard options
        bot.send_message(message.chat.id, transcription, reply_markup=markup)

    finally:
        # Release the semaphore to allow another user to process
        sem.release()

@bot.message_handler(commands=['start'])
def send_welcome(message: Message):
    bot.reply_to(message, "Welcome! Please send a voice or sound file for transcription.")

@bot.message_handler(content_types=['voice', 'audio'])
def handle_voice(message: Message):
    # If there are more than 5 active requests, add the request to the queue
    if request_queue.qsize() >= 5:
        bot.reply_to(message, "We are currently processing other requests. You have been added to the queue, please wait...")
        request_queue.put(message)
    else:
        # Process the request immediately if under the 5-user limit
        thread = threading.Thread(target=process_request, args=(message,))
        thread.start()

# Background worker to handle queued requests
def process_queue():
    while True:
        message = request_queue.get()
        if message:
            process_request(message)
            request_queue.task_done()

@bot.message_handler(func=lambda message: True)
def handle_text(message: Message):
    if message.text == "Correction":
        # Get the latest transcription for the user
        transcription = user_transcriptions.get(message.from_user.id)
        if transcription:
            # Send "Please wait..." message
            wait_message = bot.send_message(message.chat.id, "Please wait...")
            # Run chat_with_gpt
            response = chat_with_gpt(transcription)
            # Delete the "Please wait..." message
            bot.delete_message(message.chat.id, wait_message.message_id)
            # Send GPT response
            bot.send_message(message.chat.id, response)

            # Keep the Reset button
            markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            reset_btn = KeyboardButton("Reset")
            markup.add(reset_btn)
            bot.send_message(message.chat.id, "You can reset the conversation.", reply_markup=markup)
        else:
            bot.send_message(message.chat.id, "No transcription found. Please send a voice message first.")
    
    elif message.text == "Reset":
        # Clear the user's transcription and reset the conversation
        if message.from_user.id in user_transcriptions:
            del user_transcriptions[message.from_user.id]

        # Remove all keyboard options (using ReplyKeyboardRemove)
        bot.send_message(message.chat.id, "The conversation has been reset.", reply_markup=ReplyKeyboardRemove())

# Start a background thread to handle the queue
queue_thread = threading.Thread(target=process_queue)
queue_thread.daemon = True
queue_thread.start()

# Start polling
bot.polling()