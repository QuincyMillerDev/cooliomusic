---
title: Music quickstart
subtitle: Learn how to generate music with Eleven Music.
---

This guide will show you how to generate music with Eleven Music.

<Info>The Eleven Music API is only available to paid users.</Info>

## Using the Eleven Music API

<Steps>
    <Step title="Create an API key">
        [Create an API key in the dashboard here](https://elevenlabs.io/app/settings/api-keys), which you’ll use to securely [access the API](/docs/api-reference/authentication).
        
        Store the key as a managed secret and pass it to the SDKs either as a environment variable via an `.env` file, or directly in your app’s configuration depending on your preference.
        
        ```js title=".env"
        ELEVENLABS_API_KEY=<your_api_key_here>
        ```
        
    </Step>
    <Step title="Install the SDK">
        We'll also use the `dotenv` library to load our API key from an environment variable.
        
        <CodeBlocks>
            ```python
            pip install elevenlabs
            pip install python-dotenv
            ```
        
            ```typescript
            npm install @elevenlabs/elevenlabs-js
            npm install dotenv
            ```
        
        </CodeBlocks>
        
    </Step>
    <Step title="Make the API request">
        Create a new file named `example.py` or `example.mts`, depending on your language of choice and add the following code:

        <CodeBlocks>
        ```python
        # example.py
        from elevenlabs.client import ElevenLabs
        from elevenlabs.play import play
        import os
        from dotenv import load_dotenv
        load_dotenv()

        elevenlabs = ElevenLabs(
            api_key=os.getenv("ELEVENLABS_API_KEY"),
        )

        track = elevenlabs.music.compose(
            prompt="Create an intense, fast-paced electronic track for a high-adrenaline video game scene. Use driving synth arpeggios, punchy drums, distorted bass, glitch effects, and aggressive rhythmic textures. The tempo should be fast, 130–150 bpm, with rising tension, quick transitions, and dynamic energy bursts.",
            music_length_ms=10000,
        )

        play(track)
        ```

        ```typescript
        // example.mts
        import { ElevenLabsClient } from "@elevenlabs/elevenlabs-js";
        import "dotenv/config";

        const elevenlabs = new ElevenLabsClient();

        const track = await elevenlabs.music.compose({
          prompt: "Create an intense, fast-paced electronic track for a high-adrenaline video game scene. Use driving synth arpeggios, punchy drums, distorted bass, glitch effects, and aggressive rhythmic textures. The tempo should be fast, 130–150 bpm, with rising tension, quick transitions, and dynamic energy bursts.",
          musicLengthMs: 10000,
        });

        await play(track);
        ```
        </CodeBlocks>
    </Step>
     <Step title="Execute the code">
        <CodeBlocks>
            ```python
            python example.py
            ```

            ```typescript
            npx tsx example.mts
            ```
        </CodeBlocks>

        You should hear the generated music playing.
    </Step>

</Steps>

## Composition plans

A composition plan is a JSON object that describes the music you want to generate in finer detail. It can then be used to generate music with Eleven Music.

Using a plan is optional, but it can be used to generate more complex music by giving you more granular control over each section of the generation.

### Generating a composition plan

A composition plan can be generated from a prompt by using the API.

<CodeBlocks>

    ```python
    from elevenlabs.client import ElevenLabs
    from elevenlabs.play import play
    import os
    from dotenv import load_dotenv
    load_dotenv()

    elevenlabs = ElevenLabs(
    api_key=os.getenv("ELEVENLABS_API_KEY"),
    )

    composition_plan = elevenlabs.music.composition_plan.create(
        prompt="Create an intense, fast-paced electronic track for a high-adrenaline video game scene. Use driving synth arpeggios, punchy drums, distorted bass, glitch effects, and aggressive rhythmic textures. The tempo should be fast, 130–150 bpm, with rising tension, quick transitions, and dynamic energy bursts.",
        music_length_ms=10000,
    )

    print(composition_plan)
    ```

    ```typescript
    import { ElevenLabsClient } from "@elevenlabs/elevenlabs-js";
    import "dotenv/config";

    const elevenlabs = new ElevenLabsClient();

    const compositionPlan = await elevenlabs.music.compositionPlan.create({
      prompt: "Create an intense, fast-paced electronic track for a high-adrenaline video game scene. Use driving synth arpeggios, punchy drums, distorted bass, glitch effects, and aggressive rhythmic textures. The tempo should be fast, 130–150 bpm, with rising tension, quick transitions, and dynamic energy bursts.",
      musicLengthMs: 10000,
    });

    console.log(JSON.stringify(compositionPlan, null, 2));
    ```

</CodeBlocks>

The above will generate a composition plan similar to the following:

```json
{
  "positiveGlobalStyles": [
    "electronic",
    "fast-paced",
    "driving synth arpeggios",
    "punchy drums",
    "distorted bass",
    "glitch effects",
    "aggressive rhythmic textures",
    "high adrenaline"
  ],
  "negativeGlobalStyles": ["acoustic", "slow", "minimalist", "ambient", "lo-fi"],
  "sections": [
    {
      "sectionName": "Intro",
      "positiveLocalStyles": [
        "rising synth arpeggio",
        "glitch fx",
        "filtered noise sweep",
        "soft punchy kick building tension"
      ],
      "negativeLocalStyles": ["soft pads", "melodic vocals", "ambient textures"],
      "durationMs": 3000,
      "lines": []
    },
    {
      "sectionName": "Peak Drop",
      "positiveLocalStyles": [
        "full punchy drums",
        "distorted bass stab",
        "aggressive rhythmic hits",
        "rapid arpeggio sequences"
      ],
      "negativeLocalStyles": ["smooth transitions", "clean bass", "slow buildup"],
      "durationMs": 4000,
      "lines": []
    },
    {
      "sectionName": "Final Burst",
      "positiveLocalStyles": [
        "glitch stutter",
        "energy burst vox chopped sample",
        "quick transitions",
        "snare rolls"
      ],
      "negativeLocalStyles": ["long reverb tails", "fadeout", "gentle melodies"],
      "durationMs": 3000,
      "lines": []
    }
  ]
}
```

### Using a composition plan

A composition plan can be used to generate music by passing it to the `compose` method.

<CodeBlocks>
    ```python
    # You can pass in composition_plan or prompt, but not both.
    composition = elevenlabs.music.compose(
        composition_plan=composition_plan,
    )

    play(composition)
    ```

    ```typescript
    // You can pass in compositionPlan or prompt, but not both.
    const composition = await elevenlabs.music.compose({
        compositionPlan,
    });

    await play(composition);
    ```

</CodeBlocks>

## Generating music with details

For each music generation a composition plan is created from the prompt. You can opt to retrieve this plan by using the detailed response endpoint.

<CodeBlocks>

    ```python
    track_details = elevenlabs.music.compose_detailed(
        prompt="Create an intense, fast-paced electronic track for a high-adrenaline video game scene. Use driving synth arpeggios, punchy drums, distorted bass, glitch effects, and aggressive rhythmic textures. The tempo should be fast, 130–150 bpm, with rising tension, quick transitions, and dynamic energy bursts.",
        music_length_ms=10000,
    )

    print(track_details.json) # json contains composition_plan and song_metadata. The composition plan will include lyrics (if applicable)
    print(track_details.filename)
    # track_details.audio contains the audio bytes
    ```

    ```typescript
    const trackDetails = await elevenlabs.music.composeDetailed({
      prompt: 'Create an intense, fast-paced electronic track for a high-adrenaline video game scene. Use driving synth arpeggios, punchy drums, distorted bass, glitch effects, and aggressive rhythmic textures. The tempo should be fast, 30–150 bpm, with rising tension, quick transitions, and dynamic energy bursts.',
      musicLengthMs: 10000,
    });

    console.log(JSON.stringify(trackDetails.json, null, 2)); // json contains composition_plan and song_metadata. The composition plan will include lyrics (if applicable)
    console.log(trackDetails.filename);
    // trackDetails.audio contains the audio bytes
    ```

</CodeBlocks>

## Coolio integration notes

- Coolio now talks to ElevenLabs with a single `POST https://api.elevenlabs.io/v1/music` call, mirroring the Stable Audio flow. We build the request body (prompt, optional composition plan, duration, model) and save the returned MP3; no SDK streaming is involved.
- Only our own session metadata is persisted. The JSON written beside each track contains the same fields as Stable Audio (`order`, `prompt`, `duration_ms`, `bpm`, etc.) plus the generated composition plan when one is used.

### Manual verification

1. Ensure `.env` contains a valid `ELEVENLABS_API_KEY`, then activate the virtualenv.
2. Run a smoke test to confirm generation succeeds:

    ```bash
    python - <<'PY'
    from pathlib import Path
    from coolio.providers.elevenlabs import ElevenLabsProvider

    provider = ElevenLabsProvider()
    out_dir = Path("output/elevenlabs_smoke")
    out_dir.mkdir(parents=True, exist_ok=True)

    track = provider.generate(
        prompt="Generate a 10 second upbeat electronica sting for QA",
        duration_ms=10_000,
        output_dir=out_dir,
        filename_base="smoke_test",
        title="SDK-free Smoke Test",
        role="test",
        use_composition_plan=False,
    )

    print("Audio:", track.audio_path)
    print("Metadata JSON:", track.metadata_path)
    PY
    ```

3. Inspect the JSON file to verify it matches the Stable Audio schema (no ElevenLabs-specific extras), then delete `output/elevenlabs_smoke` if it was only needed for validation.

For longer tracks or session repairs, rerun `coolio repair <session_id> --slots …` once the smoke test succeeds—the same direct request path is used, so the behavior is identical to Stable Audio.

## Copyrighted material

Attempting to generate music or a composition plan that contains copyrighted material will result in an error. This includes mentioning a band or musician by name or using copyrighted lyrics.

### Prompts with copyrighted material

In these cases, the API will return a `bad_prompt` error that contains a suggestion of what prompt you could use instead.

<CodeBlocks>
    ```python
    try:
        # This will result in a bad_prompt error
        track = elevenlabs.music.compose(
            prompt="A song that sounds like 'Bohemian Rhapsody'",
            music_length_ms=10000,
        )
      except Exception as e:
          if e.body['detail']['status'] == 'bad_prompt':
              prompt_suggestion = e.body['detail']['data']['prompt_suggestion']
              print(prompt_suggestion) # Prints: An epic rock ballad with dramatic tempo changes, operatic harmonies, and a narrative structure that blends melancholy with bursts of theatrical intensity.

              # Use the prompt suggestion to generate the track instead
    ```

    ```typescript
    try {
      // This will result in a bad_prompt error
      const track = await elevenlabs.music.compose({
        prompt: "A song that sounds like 'Bohemian Rhapsody'",
        musicLengthMs: 10000,
      });
    } catch (error) {
      if (error.body.detail.status === 'bad_prompt') {
        const promptSuggestion = error.body.detail.data.prompt_suggestion;
        console.log(promptSuggestion); // Logs: An epic rock ballad with dramatic tempo changes, operatic harmonies, and a narrative structure that blends melancholy with bursts of theatrical intensity.

        // Use the prompt suggestion to generate the track instead
      }
    }
    ```

</CodeBlocks>

### Composition plans with copyrighted material

If styles using copyrighted material are used when generating a composition plan, a `bad_composition_plan` error will be returned. Similar to music prompts, a suggested composition plan `composition_plan_suggestion` will be returned within the error.

<Warning>
  In the case of a composition plan or prompt that contains harmful material, no suggested prompt
  will be returned.
</Warning>

## Next steps

Explore the [API reference](/docs/api-reference/music/compose) for more information on the Music API and its options.

---
title: Music streaming
subtitle: Learn how to stream music with Eleven Music.
---

This guide will show you how to stream music with Eleven Music.

<Info>The Eleven Music API is only available to paid users.</Info>

## Using the Eleven Music API

<Steps>
    <Step title="Create an API key">
        [Create an API key in the dashboard here](https://elevenlabs.io/app/settings/api-keys), which you’ll use to securely [access the API](/docs/api-reference/authentication).
        
        Store the key as a managed secret and pass it to the SDKs either as a environment variable via an `.env` file, or directly in your app’s configuration depending on your preference.
        
        ```js title=".env"
        ELEVENLABS_API_KEY=<your_api_key_here>
        ```
        
    </Step>
    <Step title="Install the SDK">
        We'll also use the `dotenv` library to load our API key from an environment variable.
        
        <CodeBlocks>
            ```python
            pip install elevenlabs
            pip install python-dotenv
            ```
        
            ```typescript
            npm install @elevenlabs/elevenlabs-js
            npm install dotenv
            ```
        
        </CodeBlocks>
        
    </Step>
    <Step title="Make the API request">
        Create a new file named `example.py` or `example.mts`, depending on your language of choice and add the following code:

        <CodeBlocks>
        ```python
        # example.py
        from elevenlabs.client import ElevenLabs
        from elevenlabs.play import play
        import os
        from io import BytesIO
        from dotenv import load_dotenv
        load_dotenv()

        elevenlabs = ElevenLabs(
            api_key=os.getenv("ELEVENLABS_API_KEY"),
        )

        stream = elevenlabs.music.stream(
            prompt="Create an intense, fast-paced electronic track for a high-adrenaline video game scene. Use driving synth arpeggios, punchy drums, distorted bass, glitch effects, and aggressive rhythmic textures. The tempo should be fast, 130–150 bpm, with rising tension, quick transitions, and dynamic energy bursts.",
            music_length_ms=10000,
        )

        # Create a BytesIO object to hold the audio data in memory
        audio_stream = BytesIO()

        # Write each chunk of audio data to the stream
        for chunk in stream:
            if chunk:
                audio_stream.write(chunk)

        # Reset stream position to the beginning
        audio_stream.seek(0)

        play(audio_stream)
        ```

        ```typescript
        // example.mts
        import { ElevenLabsClient, play } from "@elevenlabs/elevenlabs-js";
        import "dotenv/config";

        const elevenlabs = new ElevenLabsClient();

        const stream = await elevenlabs.music.stream({
          prompt: "Create an intense, fast-paced electronic track for a high-adrenaline video game scene. Use driving synth arpeggios, punchy drums, distorted bass, glitch effects, and aggressive rhythmic textures. The tempo should be fast, 130–150 bpm, with rising tension, quick transitions, and dynamic energy bursts.",
          musicLengthMs: 10000,
        });

        const chunks: Buffer[] = [];

        for await (const chunk of stream) {
            chunks.push(chunk);
        }

        const audioStream = Buffer.concat(chunks);

        await play(audioStream);
        ```
        </CodeBlocks>
    </Step>
     <Step title="Execute the code">
        <CodeBlocks>
            ```python
            python example.py
            ```

            ```typescript
            npx tsx example.mts
            ```
        </CodeBlocks>

        You should hear the generated music playing.
    </Step>

</Steps>

## Next steps

Explore the [API reference](/docs/api-reference/music/stream) for more information on the Speech to Text API and its options.
