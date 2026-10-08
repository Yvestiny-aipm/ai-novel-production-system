# Stage 12 real-model test fixture V1

Purpose: give real-model tests the same Tide-Mark Archive starter pack. The default seed is still 5 scenes; scale tests use `REAL_TEST_SCENE_COUNT` to seed 20 or more, two scenes per chapter. Each scene targets about 1250 words.

Entry: `integration/run_real_test.py`

Preconditions:

- Set `RUN_REAL_MODEL=1`
- Set `SILICONFLOW_API_KEY`
- Use the DeepSeek route in `backend/model_profiles.json`
- First create this book, 5 scenes, TaskState, and the initial ContextPack in the test database
- Do not write a real API key into this file or commit it to GitHub

## 1. CreativeBrief

### Title

Tide-Mark Archive

### Genre

Near-future science-fiction mystery

### Theme

When a city puts "safety" above personal memory and choice, does a person still have the right to know the truth and accept the cost of choosing?

### Protagonist

Lin Zhao, 29, a public-archive restorer in Tide-Edge City. She repairs damaged memory media. She is careful, evidence-first, and acts only after the facts hold. Her younger sister Lin Lan vanished in a tsunami three years ago. Official records say she is dead. No body was found.

### World

Tide-Edge City is built on sea platforms. A lighthouse system manages tide warnings, resident records, and evacuation routes. Everyone wears an Echo Chip that can record and play back a fragment of personal memory. The city is preparing a large sea evacuation. Officials have not published the full reason.

### Core rules

1. An Echo Chip can play back only one complete memory at a time.
2. After a wearer plays back someone else's memory, they permanently lose their own most recent memory of equal length.
3. The lighthouse system may only store, retrieve, and display memory. It cannot rewrite a person's memory.
4. An archivist may read an Echo Chip only with the wearer's authorization or emergency-rescue authorization.
5. A tide warning is issued 24 hours in advance. After a formal warning is published, an ordinary archivist cannot withdraw it.

### Main conflict

Lin Zhao finds that her sister may have left a hidden memory before vanishing. Before the city starts a forced evacuation, she must judge whether that memory is trustworthy and decide whether to publish the truth or obey the lighthouse lock.

## 2. Consecutive scene cards

### Scene 1: The damaged Echo Chip

- Scene goal: let Lin Zhao discover that her sister may still have left a clue.
- Entrance: Lin Zhao is restoring ordinary residents' flood memories in the public archive. She has no new clue about her sister.
- Characters: Lin Zhao, colleague Zhou Cen, archive clerk on duty.
- Location: restoration room, Tide-Edge City public archive.
- Conflict: a damaged Echo Chip labeled "Lin Lan" is mixed into files marked for destruction.
- Must happen: Lin Zhao confirms the chip number matches her sister's identity file; she cannot play the chip because she has no authorization.
- Must not happen: Lin Zhao must not learn in this scene that her sister is confirmed alive; the lighthouse must not rewrite the chip.
- Exit: Lin Zhao moves the chip into an isolation cabinet and decides to seek emergency-rescue authorization.
- Continuity: the chip has not been played; Lin Zhao still does not know its contents; Zhou Cen knows she found an anomaly.
- Acceptance: rule 3, rule 4, the character's caution.

### Scene 2: The deleted twenty-seven minutes

- Scene goal: play the chip under legal authorization and obtain a place clue her sister left.
- Entrance: Lin Zhao has isolated the chip and is applying for emergency-rescue authorization.
- Characters: Lin Zhao, Zhou Cen, remote duty officer.
- Location: archive isolation room; old sea-metro entrance.
- Conflict: authorization is about to expire. Lin Zhao must decide whether to pay the cost of losing her own memory.
- Must happen: Lin Zhao receives emergency-rescue authorization and plays the memory; she sees her sister leave a "blue tide mark" at the old sea-metro station.
- Must not happen: playback must not give Lin Zhao more than the memory contains; it must not break "one playback, lose an equal length of recent memory."
- Exit: Lin Zhao confirms the clue points to the old sea-metro station and loses her most recent twenty-seven minutes.
- Continuity: Lin Zhao does not remember leaving the isolation room after playback; the chip gives a place, not whether her sister is alive.
- Acceptance: rule 1, rule 2, state handoff.

### Scene 3: The blue tide mark

- Scene goal: Lin Zhao and Zhou Cen go to the old sea-metro station and find the second-layer clue her sister left.
- Entrance: Lin Zhao knows the place but is missing the twenty-seven minutes after playback; Zhou Cen knows part of what happened but has not seen the full memory.
- Characters: Lin Zhao, Zhou Cen, lighthouse inspector Shen Yan.
- Location: old sea-metro station; closed tide-maintenance passage.
- Conflict: the inspector tells them to leave. Lin Zhao must prove she has authorization. The blue tide mark points to an unpublished evacuation list.
- Must happen: Lin Zhao finds her sister's signature and a set of evacuation numbers; Shen Yan confirms the passage will close after the tide warning.
- Must not happen: Lin Zhao must not recover the lost memory; the lighthouse must not suddenly change the evacuation list; the sister must not appear in person.
- Exit: Lin Zhao has the evacuation numbers and finds her sister may be listed as an unpublished evacuee.
- Continuity: carry scene 2's place clue and memory gap; the list is not yet proven official.
- Acceptance: character behavior, plot advance, the memory gap stays consistent.

### Scene 4: The lighthouse does not lie

- Scene goal: Lin Zhao checks the evacuation numbers and finds human access traces in the lighthouse archive.
- Entrance: Lin Zhao holds unpublished evacuation numbers but cannot confirm her sister is on the list; the city is less than 24 hours from a formal tide warning.
- Characters: Lin Zhao, Zhou Cen, archive director Gu Xian.
- Location: main control Archive Room of the public archive.
- Conflict: the director tells Lin Zhao to return the chip and stop querying; system logs show someone used human privileges to access the evacuation file.
- Must happen: Lin Zhao confirms the access record through a formal archive query; she must not blame the lighthouse system itself for the anomaly.
- Must not happen: do not break the rule that the lighthouse may only store and display memory; do not confirm the director is the hidden operator.
- Exit: Lin Zhao confirms the file was accessed by a person, and the access time is close to her sister's disappearance.
- Continuity: scene 3's evacuation numbers are partly verified; whether the sister is alive is still unconfirmed.
- Acceptance: world-rule consistency, evidence strength, mystery pacing.

### Scene 5: Open Tide

- Scene goal: before the formal tide warning, Lin Zhao decides whether to publish the archive anomaly and her sister's clue.
- Entrance: Lin Zhao has the chip, the evacuation numbers, and the human-access log, but no complete proof of the hidden operator.
- Characters: Lin Zhao, Zhou Cen, Gu Xian, lighthouse broadcast system.
- Location: public-archive broadcast hall.
- Conflict: Gu Xian wants the files sealed. The lighthouse is about to publish a formal tide warning. Lin Zhao must accept the cost of publishing with incomplete proof.
- Must happen: Lin Zhao publishes the confirmed facts and the scope of the evidence; she clearly separates fact, inference, and unknown.
- Must not happen: do not treat "the sister is alive" as a confirmed fact; do not let the lighthouse withdraw a formal warning already published.
- Exit: the archive anomaly and unpublished evacuation numbers are public. The sister's life or death remains an open question.
- Continuity: carry scene 4's log evidence; the ending may continue later investigation, but must not invent the unknown truth.
- Acceptance: fact vs inference, world rules, ending direction, and the memory proposal.

### Scenes 6–20: scale continuation

Scene cards 1–5 still stand. From scene 6 on, do not prewrite scene-by-scene outlines. The planning agent continues from the CreativeBrief, world rules, and the previous `accepted_scene_state`. Constraints:

- Still the same book, two scenes per chapter. 20 scenes map to chapters 1–10.
- Do not announce the book is over. Do not confirm Lin Lan is dead or safely home.
- The lighthouse may only store, retrieve, and display memory. It cannot rewrite memory.
- Each scene must have new, prose-provable advance. Do not only repeat facts already published in the first five scenes.

## 3. ContextPack checks

Before each scene, check:

- The correct `brief_version` is read.
- The previous `accepted_scene_state` is read.
- Needed rules and character state are included.
- Pending MemoryProposal items are excluded.
- Source versions, exclusions, missing items, and the snapshot hash are recorded.
- The current `plan_version`, `scene_id`, and `target_agent` are bound.

State handoff to watch:

```text
Scene 1: chip not played
Scene 2: playback gives a place; twenty-seven minutes of memory are lost
Scene 3: memory gap kept; evacuation numbers found
Scene 4: human-access log confirmed
Scene 5: confirmed facts published; sister's life or death still unknown
```

## 4. Stage 12 test record

Each scene should at least record:

- Task id
- Scene number
- ContextPack version
- Plan version
- Draft version and draft hash
- Three reviewer results
- Whether writing was reworked
- Whether a MemoryProposal was produced
- Whether `accepted_scene_state` was updated
- Harness call id
- Model, elapsed time, and usage

Real-model tests should at least cover:

- One scene completed normally
- One scene that reworks writing or is human-restarted
- One scene that produces a memory proposal
- State handoff across five scenes
- Switching APIs by changing Harness config only, not business code
