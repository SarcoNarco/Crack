import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

const SAMPLE_RATE = 22050
const OUTPUT = resolve(new URL('..', import.meta.url).pathname, 'public/map/audio')

function envelope(t, duration, attack = 0.008, release = 0.06) {
  const rise = Math.min(1, t / attack)
  const fall = Math.min(1, (duration - t) / release)
  return Math.max(0, Math.min(rise, fall))
}

function tone(t, frequency, duration, amplitude, phase = 0) {
  return Math.sin((Math.PI * 2 * frequency * t) + phase) * amplitude * envelope(t, duration)
}

function cueSamples(name, duration) {
  const count = Math.round(SAMPLE_RATE * duration)
  return Array.from({ length: count }, (_, index) => {
    const t = index / SAMPLE_RATE
    let value = 0
    if (name === 'footsteps') {
      value = tone(t, 115, duration, 0.18) + tone(Math.max(0, t - 0.13), 140, duration - 0.13, 0.15)
    } else if (name === 'scan') {
      value = tone(t, 420 + (t / duration) * 480, duration, 0.12) + tone(t, 840 + (t / duration) * 320, duration, 0.035)
    } else if (name === 'probe') {
      value = tone(t, 1160, duration, 0.15) + tone(t, 1640, duration, 0.045)
    } else if (name === 'pickaxe') {
      value = tone(t, 92, duration, 0.18) + tone(t, 760, duration, 0.11, 0.4) + tone(t, 1320, duration, 0.04)
    } else if (name === 'beam') {
      value = tone(t, 520 + (t / duration) * 900, duration, 0.11) + tone(t, 1040, duration, 0.035)
    } else if (name === 'consensus') {
      value = tone(t, 520, duration, 0.12) + tone(t, 780, duration, 0.06) + tone(Math.max(0, t - 0.12), 1040, duration - 0.12, 0.09)
    } else if (name === 'failure') {
      value = tone(t, 420 - (t / duration) * 190, duration, 0.12) + tone(t, 210 - (t / duration) * 55, duration, 0.045)
    }
    return Math.max(-1, Math.min(1, value))
  })
}

function wav(samples) {
  const dataSize = samples.length * 2
  const output = Buffer.alloc(44 + dataSize)
  output.write('RIFF', 0)
  output.writeUInt32LE(36 + dataSize, 4)
  output.write('WAVE', 8)
  output.write('fmt ', 12)
  output.writeUInt32LE(16, 16)
  output.writeUInt16LE(1, 20)
  output.writeUInt16LE(1, 22)
  output.writeUInt32LE(SAMPLE_RATE, 24)
  output.writeUInt32LE(SAMPLE_RATE * 2, 28)
  output.writeUInt16LE(2, 32)
  output.writeUInt16LE(16, 34)
  output.write('data', 36)
  output.writeUInt32LE(dataSize, 40)
  samples.forEach((sample, index) => output.writeInt16LE(Math.round(sample * 32767), 44 + index * 2))
  return output
}

const cues = {
  footsteps: 0.28,
  scan: 0.4,
  probe: 0.21,
  pickaxe: 0.22,
  beam: 0.32,
  consensus: 0.34,
  failure: 0.38,
}

mkdirSync(OUTPUT, { recursive: true })
for (const [name, duration] of Object.entries(cues)) {
  const target = resolve(OUTPUT, `${name}.wav`)
  mkdirSync(dirname(target), { recursive: true })
  writeFileSync(target, wav(cueSamples(name, duration)))
}
