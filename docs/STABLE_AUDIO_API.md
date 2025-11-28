Text-to-Audio
Stable Audio generates high-quality music and sound effects up to three minutes long at 44.1kHz stereo from text descriptions. Learn how to craft effective prompts in our Prompt Guide to get the best results from your generations.

Try it out
Grab your API key and head over to Open Google Colab or try Stable Audio 2.0 for free at stableaudio.com.

How to use
Please invoke this endpoint with a POST request.

The headers of the request must include an API key in the authorization field. The body of the request must be multipart/form-data. The accept header should be set to one of the following:

audio/* to receive the audio in the format specified by the output_format parameter.
application/json to receive the audio encoded as base64 in a JSON response.
The body of the request should include:

prompt - text to generate the audio from. Check our prompt guide for tips
Optional Parameters:
The body may optionally include:

output_format - the format of the output audio
seed - the randomness seed to use for the generation
steps - the number of sampling steps
duration - the number of seconds of the generated audio
cfg_scale - controls how strictly the diffusion process adheres to the prompt text (only for stable-audio-2)
model - the model to use [stable-audio-2, stable-audio-2.5]
Note: for more details about these parameters please see the request schema below.

Credits
Stable Audio 2.0

By default, 20 credits per successful generation. The number of credits is determined by the following formula: credits = 17 + 0.06 * steps.

Examples:

50 steps = 20 credits [default]
100 steps = 23 credits
Stable Audio 2.5

Requests made using the Stable Audio 2.5 model have a flat rate of 20 credits per successful result.

As always, you will not be charged for failed generations.

Authorizations:
STABILITY_API_KEY
header Parameters
authorization
required
string non-empty
Your Stability API key, used to authenticate your requests. Although you may have multiple keys in your account, you should use the same key for all requests to this API.

content-type
required
string non-empty
Example: multipart/form-data
The content type of the request body. Do not manually specify this header; your HTTP client library will automatically include the appropriate boundary parameter.

accept	
string
Default: audio/*
Enum: application/json audio/*
Specify audio/* to receive the bytes of the audio directly. Otherwise specify application/json to receive the audio as base64 encoded JSON.

stability-client-id	
string (StabilityClientID) <= 256 characters
Example: my-awesome-app
The name of your application, used to help us communicate app-specific debugging or moderation issues to you.

stability-client-user-id	
string (StabilityClientUserID) <= 256 characters
Example: DiscordUser#9999
A unique identifier for your end user. Used to help us communicate user-specific debugging or moderation issues to you. Feel free to obfuscate this value to protect user privacy.

stability-client-version	
string (StabilityClientVersion) <= 256 characters
Example: 1.2.1
The version of your application, used to help us communicate version-specific debugging or moderation issues to you.

Request Body schema: multipart/form-data
prompt
required
string <= 10000 characters
What you wish the output audio to be. A strong, descriptive prompt that clearly defines instruments, moods, styles, and genre will lead to better results.

You can make a prompt as simple or complex as you like. Simple prompts are good for clean output audio. Complex prompts are good for adding texture and depth to the output audio.

Check our prompt guide for tips.

duration	
number [ 1 .. 190 ]
Default: 190
Controls the duration in seconds of the generated audio.

seed	
number [ 0 .. 4294967294 ]
Default: 0
A specific value that is used to guide the 'randomness' of the generation. (Omit this parameter or pass 0 to use a random seed.)

steps	
integer
Controls the number of sampling steps.

For stable-audio-2: accepts steps between 30 and 100 (defaults to 50).
For stable-audio-2.5: accepts steps between 4 and 8 (defaults to 8).
cfg_scale	
number [ 1 .. 25 ]
How strictly the diffusion process adheres to the prompt text (higher values make your audio closer to your prompt).

Defaults to 7 for stable-audio-2 and 1 for stable-audio-2.5 if not specified.

model	
string
Default: stable-audio-2
Enum: stable-audio-2 stable-audio-2.5
The model to use for generation.

stable-audio-2.5 requires 20 credits per generation
stable-audio-2 requires 20 credits per generation
output_format	
string
Default: mp3
Enum: mp3 wav
Dictates the content-type of the generated audio.

Responses
200
Generation was successful.

400
Invalid parameter(s), see the errors field for details.

403
Your request was flagged by our content moderation system.

422
Your request was well-formed, but rejected. See the errors field for details.

429
You have made more than 150 requests in 10 seconds.

500
An internal error occurred. If the problem persists contact support.