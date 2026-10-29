import assert from "node:assert/strict";
import { getPlayableAudioUrl, audioSchedule, stopAudioPlayback, findAudioSourceClip, extractWavOutput, buildAudioTrackEntry } from "../static/js/tabs/timeline.js";

console.log("--- Iniciando tests de lógica de Audio Multi-Pista de Timeline (Node) ---");

// Test 1: getPlayableAudioUrl resuelve URLs y paths web y descarta paths de disco local
{
  assert.equal(getPlayableAudioUrl({ url: "/media/audio1.mp3" }), "/media/audio1.mp3");
  assert.equal(getPlayableAudioUrl({ url: "https://example.com/sound.ogg" }), "https://example.com/sound.ogg");
  assert.equal(getPlayableAudioUrl({ source_path: "/media/uploads/bg.mp3" }), "/media/uploads/bg.mp3");
  assert.equal(getPlayableAudioUrl({ source_path: "blob:http://localhost:8765/abc-123" }), "blob:http://localhost:8765/abc-123");
  assert.equal(getPlayableAudioUrl({ source_path: "C:\\audio\\track.mp3" }), "", "Debe ignorar paths de disco Windows sin url");
  assert.equal(getPlayableAudioUrl({ source_path: "D:/audio/track.mp3" }), "", "Debe ignorar paths absolutos con letra de unidad sin url");
  assert.equal(getPlayableAudioUrl({ url: "", source_path: "" }), "", "Debe devolver string vacío si no hay ruta");
  assert.equal(getPlayableAudioUrl(null), "");
  console.log("✔ Test 1: getPlayableAudioUrl resuelve URLs web válidas y descarta rutas de disco locales");
}

// Test 2: audioSchedule ignora pistas muteadas (mute o muted)
{
  const tracks = [
    { url: "/media/track1.mp3", start_time: 0, volume: 1.0, mute: true },
    { url: "/media/track2.mp3", start_time: 1.0, volume: 0.8, muted: true },
    { url: "/media/track3.mp3", start_time: 2.0, volume: 0.5 },
  ];
  const scheduled = audioSchedule(tracks);
  assert.equal(scheduled.length, 1, "Solo la pista no muteada debe programarse");
  assert.equal(scheduled[0].url, "/media/track3.mp3");
  assert.equal(scheduled[0].startTime, 2.0);
  assert.equal(scheduled[0].volume, 0.5);
  console.log("✔ Test 2: audioSchedule ignora pistas muteadas (mute=true / muted=true)");
}

// Test 3: audioSchedule maneja start_time = 0 (inmediato) y start_time > 0 (diferido)
{
  const tracks = [
    { url: "/media/bgm.mp3", start_time: 0, volume: 0.7 },
    { url: "/media/sfx.mp3", start_time: 3.5, volume: 1.0 },
  ];
  const scheduled = audioSchedule(tracks);
  assert.equal(scheduled.length, 2);

  assert.equal(scheduled[0].immediate, true, "Pista con start_time 0 es inmediata");
  assert.equal(scheduled[0].startTime, 0);

  assert.equal(scheduled[1].immediate, false, "Pista con start_time 3.5 no es inmediata");
  assert.equal(scheduled[1].startTime, 3.5);
  console.log("✔ Test 3: audioSchedule detecta pistas inmediatas y diferidas por start_time");
}

// Test 4: audioSchedule normaliza y clampa el volumen al rango [0.0, 1.0]
{
  const tracks = [
    { url: "/media/loud.mp3", start_time: 0, volume: 1.8 },
    { url: "/media/silent.mp3", start_time: 0, volume: -0.5 },
    { url: "/media/default.mp3", start_time: 0, volume: null },
  ];
  const scheduled = audioSchedule(tracks);
  assert.equal(scheduled[0].volume, 1.0, "Volumen > 1.0 se clampa a 1.0");
  assert.equal(scheduled[1].volume, 0.0, "Volumen < 0.0 se clampa a 0.0");
  assert.equal(scheduled[2].volume, 1.0, "Volumen no numérico usa 1.0 por defecto");
  console.log("✔ Test 4: audioSchedule normaliza y clampa el volumen en rango válido");
}

// Test 5: Pista sin URL reproducible no rompe las demás
{
  const tracks = [
    { url: "", source_path: "E:\\raw\\unreachable.mp3", start_time: 0 },
    { url: "/media/valid.mp3", start_time: 1.2, volume: 0.9 },
    null,
    { url: "   ", start_time: 2.0 },
    { url: "/media/valid2.mp3", start_time: 0, volume: 0.4 },
  ];
  const scheduled = audioSchedule(tracks);
  assert.equal(scheduled.length, 2, "Debe omitir pistas inválidas o nulas sin lanzar error");
  assert.equal(scheduled[0].url, "/media/valid.mp3");
  assert.equal(scheduled[1].url, "/media/valid2.mp3");
  console.log("✔ Test 5: audioSchedule omite pistas sin URL reproducible sin romper las demás");
}

// Test 6: stopAudioPlayback no lanza errores y puede ejecutarse sin audios activos
{
  assert.doesNotThrow(() => {
    stopAudioPlayback();
  }, "stopAudioPlayback debe ser seguro de invocar en cualquier estado");
  console.log("✔ Test 6: stopAudioPlayback es idempotente y seguro");
}

// Test 7: findAudioSourceClip elige el primer clip de vídeo con generation_id
{
  const clips = [
    { kind: "image", generation_id: 10 },
    { kind: "video", generation_id: null },
    { kind: "video", generation_id: 22 },
    { kind: "video", generation_id: 33 },
  ];
  assert.equal(findAudioSourceClip(clips).generation_id, 22);
  assert.equal(findAudioSourceClip([{ kind: "image", generation_id: 1 }]), null);
  assert.equal(findAudioSourceClip(null), null);
  assert.equal(findAudioSourceClip([]), null);
  console.log("✔ Test 7: findAudioSourceClip elige el primer vídeo con generation_id");
}

// Test 8: extractWavOutput localiza el WAV entre las salidas del job
{
  assert.deepEqual(
    extractWavOutput({
      outputs: [
        { name: "video_audio_7.mp4", url: "/media/7/video_audio_7.mp4" },
        { name: "audio_7.wav", url: "/media/7/audio_7.wav" },
      ],
    }),
    { name: "audio_7.wav", url: "/media/7/audio_7.wav" }
  );
  assert.deepEqual(extractWavOutput({ outputs: ["audio_8.WAV"] }), { name: "audio_8.WAV", url: "" });
  assert.equal(extractWavOutput({ outputs: [{ name: "solo.mp4" }] }), null);
  assert.equal(extractWavOutput(null), null);
  console.log("✔ Test 8: extractWavOutput devuelve el WAV y su URL");
}

// Test 9: buildAudioTrackEntry crea una pista válida para Timeline
{
  assert.deepEqual(
    buildAudioTrackEntry({ audio_path: "E:\\data\\audio\\a.wav", audio_url: "/media/audio/a.wav" }),
    { source_path: "E:\\data\\audio\\a.wav", url: "/media/audio/a.wav", start_time: 0, volume: 1.0 }
  );
  assert.deepEqual(
    buildAudioTrackEntry({ audio_url: "/media/audio/b.wav" }),
    { source_path: "/media/audio/b.wav", url: "/media/audio/b.wav", start_time: 0, volume: 1.0 }
  );
  console.log("✔ Test 9: buildAudioTrackEntry prepara la pista del Timeline");
}

console.log("=== TODOS LOS TESTS DE TIMELINE AUDIO PASARON EXITOSAMENTE ===");
