/**
 * App.jsx  -  THE MAIN SCREEN
 * ============================
 * A text box (or microphone!) to talk to the agent, and the live Procurement Log.
 *
 * VOICE INPUT WITHOUT ANY API KEY
 *   Browsers have a built-in speech-to-text feature called the Web Speech API.
 *   We just switch it on. It needs no key and no account. Things to know:
 *     - It works in Chrome, Edge and Safari. Firefox does not support it.
 *     - The browser asks for microphone permission the first time.
 *     - It needs internet. (Chrome sends the audio to Google's speech service
 *       by itself. That is the browser's job, not ours, and costs you nothing.)
 *     - It only works on https:// pages or on http://localhost.
 */
import { useRef, useState } from "react";
import ProcurementGrid from "./components/ProcurementGrid";

// Empty = "same address as this page" (works with Vite's proxy and with Docker/nginx).
// For a separate frontend host (like Render's static sites) set VITE_API_URL when building.
const API_URL = import.meta.env.VITE_API_URL || "";

// The browser's speech feature (Safari/Chrome call it by different names).
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

// Friendly messages for the things that can go wrong with the microphone.
const VOICE_ERRORS = {
  "not-allowed": "Microphone is blocked. Allow the microphone for this page and try again.",
  "service-not-allowed": "Microphone is blocked. Allow the microphone for this page and try again.",
  "no-speech": "I didn't hear anything. Click the microphone and try again.",
  "audio-capture": "No microphone found.",
  network: "Voice needs an internet connection.",
};

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [autoSend, setAutoSend] = useState(true);
  const [voiceNote, setVoiceNote] = useState("");

  // Refs hold values that the speech callbacks need to read at the latest moment.
  const recognition = useRef(null);
  const autoSendRef = useRef(true);
  const heardText = useRef("");

  // Send the request to the backend agent.
  async function askAgent(text) {
    const request = (text ?? prompt).trim();
    if (!request || busy) return;
    setBusy(true);
    setReply("");
    try {
      const response = await fetch(`${API_URL}/api/agent/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: request }),
      });
      const data = await response.json();
      // On errors FastAPI sends {detail: "..."}; on success {message: "..."}.
      setReply(data.message || data.detail || "No reply");
    } catch (e) {
      setReply("Could not reach the backend: " + e.message);
    }
    setBusy(false);
  }

  // Click the microphone: start listening. Click again: stop.
  function toggleVoice() {
    if (listening) {
      recognition.current?.stop();
      return;
    }
    const rec = new SpeechRecognition();
    rec.lang = navigator.language || "en-US";
    rec.interimResults = true; // show words while you are still speaking
    rec.continuous = false; // stop by itself after you finish a sentence
    heardText.current = "";

    rec.onstart = () => {
      setListening(true);
      setVoiceNote("Listening... speak now");
    };
    rec.onresult = (event) => {
      // Join everything heard so far and show it in the text box.
      let text = "";
      for (let i = 0; i < event.results.length; i++) text += event.results[i][0].transcript;
      setPrompt(text);
      heardText.current = text;
    };
    rec.onerror = (event) => setVoiceNote(VOICE_ERRORS[event.error] || `Voice problem: ${event.error}`);
    rec.onend = () => {
      setListening(false);
      const text = heardText.current.trim();
      if (!text) return;
      if (autoSendRef.current) {
        setVoiceNote(`Heard: "${text}". Sending...`);
        askAgent(text);
      } else {
        setVoiceNote(`Heard: "${text}". Check it, then click Ask agent.`);
      }
    };
    recognition.current = rec;
    try {
      rec.start();
    } catch (e) {
      setVoiceNote("Could not start the microphone: " + e.message);
    }
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 1200, margin: "0 auto" }}>
      {/* Small style block: the microphone pulses red while listening. */}
      <style>{`
        @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(220,38,38,.5); } 100% { box-shadow: 0 0 0 14px rgba(220,38,38,0); } }
        .mic { border: 1px solid #ccc; background: #fff; border-radius: 50%; width: 42px; height: 42px; font-size: 20px; cursor: pointer; }
        .mic.on { background: #dc2626; color: #fff; border-color: #dc2626; animation: pulse 1.2s infinite; }
        .mic:disabled { opacity: .4; cursor: not-allowed; }
      `}</style>

      <h1 style={{ padding: "16px 16px 0" }}>PalCart</h1>

      <div style={{ padding: 16, display: "flex", gap: 8, alignItems: "center" }}>
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && askAgent()}
          placeholder="What should I buy? For example: a LEGO set under $30"
          style={{ flex: 1, padding: 10, fontSize: 16 }}
        />
        <button
          className={"mic" + (listening ? " on" : "")}
          onClick={toggleVoice}
          disabled={!SpeechRecognition}
          title={SpeechRecognition ? (listening ? "Stop listening" : "Speak your request") : "Voice input needs Chrome, Edge or Safari"}
          aria-label="Voice input"
        >
          &#127908;
        </button>
        <button onClick={() => askAgent()} disabled={busy || !prompt.trim()} style={{ padding: "10px 16px" }}>
          {busy ? "Thinking..." : "Ask agent"}
        </button>
      </div>

      {SpeechRecognition && (
        <div style={{ padding: "0 16px", fontSize: 14, color: "#555", display: "flex", gap: 16, alignItems: "center" }}>
          <label>
            <input
              type="checkbox"
              checked={autoSend}
              onChange={(e) => {
                setAutoSend(e.target.checked);
                autoSendRef.current = e.target.checked;
              }}
            />{" "}
            Send automatically when I finish speaking
          </label>
          {voiceNote && <span>{voiceNote}</span>}
        </div>
      )}
      {!SpeechRecognition && (
        <p style={{ padding: "0 16px", fontSize: 14, color: "#555" }}>
          Voice input needs Chrome, Edge or Safari. You can still type your request.
        </p>
      )}

      {reply && <p style={{ padding: "0 16px" }}>🤖 {reply}</p>}
      <ProcurementGrid />
    </div>
  );
}
