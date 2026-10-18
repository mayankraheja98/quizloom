import { useEffect, useRef, useState } from "react";
import {
  getLabels,
  getQuestions,
  deleteQuestion,
  deleteLabel,
  uploadFile,
  getLabelStatus,
  generateFromTopic,
  fromNotion,
  getProviders,
} from "../api/client";

const PROVIDER_META = {
  ollama: { label: "Ollama (local)", color: "indigo", keyUrl: null },
  groq:   { label: "Groq (free)",   color: "green",  keyUrl: "https://console.groq.com/keys" },
  gemini: { label: "Gemini (free)", color: "blue",   keyUrl: "https://aistudio.google.com/app/apikey" },
};

// ── Per-user saved LLM settings (localStorage, keyed by username) ─────────────
const prefsKey = () => `examprep:llm:${localStorage.getItem("username") || "anon"}`;
const readPrefs = () => {
  try { return JSON.parse(localStorage.getItem(prefsKey())) || {}; } catch { return {}; }
};
const writePrefs = (fn) => {
  try { localStorage.setItem(prefsKey(), JSON.stringify(fn(readPrefs()))); } catch { /* storage unavailable */ }
};
const clearPrefs = () => { try { localStorage.removeItem(prefsKey()); } catch { /* ignore */ } };

function useLLMPrefs(defaultModel = "gemma3:4b") {
  const [init] = useState(readPrefs);
  const startProvider = init.lastProvider || "ollama";
  const [provider, setProviderRaw] = useState(startProvider);
  const [model, setModel] = useState(init.providers?.[startProvider]?.model || defaultModel);
  const [apiKey, setApiKey] = useState(init.providers?.[startProvider]?.apiKey || "");

  // Persist (read-modify-write so the three forms don't clobber each other)
  useEffect(() => {
    writePrefs((p) => ({
      ...p,
      lastProvider: provider,
      providers: { ...p.providers, [provider]: { model, apiKey } },
    }));
  }, [provider, model, apiKey]);

  // Switching provider restores that provider's saved model/key, else a sensible default
  const setProvider = (next, fallbackModel = "") => {
    const saved = readPrefs().providers?.[next] || {};
    setProviderRaw(next);
    setModel(saved.model || fallbackModel);
    setApiKey(saved.apiKey || "");
  };
  return { provider, setProvider, model, setModel, apiKey, setApiKey };
}

function ProviderFields({ provider, setProvider, model, setModel, apiKey, setApiKey, providers }) {
  const meta = PROVIDER_META[provider] || {};
  const suggested = providers[provider]?.suggested_models || [];
  return (
    <div className="flex flex-wrap gap-3 items-end">
      {/* Provider */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Provider</label>
        <select value={provider} onChange={(e) => {
            const next = e.target.value;
            setProvider(next, providers[next]?.suggested_models?.[0] || (next === "ollama" ? "gemma3:4b" : ""));
          }}
          className="border rounded px-3 py-1.5 text-sm">
          {Object.entries(PROVIDER_META).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>
      </div>
      {/* Model */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Model</label>
        <input
          type="text"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={suggested[0] || "model name"}
          list={`models-${provider}`}
          className="border rounded px-3 py-1.5 text-sm w-52"
        />
        <datalist id={`models-${provider}`}>
          {suggested.map((m) => <option key={m} value={m} />)}
        </datalist>
      </div>
      {/* API Key — shown for cloud providers */}
      {provider !== "ollama" && (
        <div className="flex-1 min-w-48">
          <label className="block text-xs text-gray-500 mb-1">
            API Key{" "}
            {meta.keyUrl && (
              <a href={meta.keyUrl} target="_blank" rel="noreferrer"
                className="text-indigo-500 underline">Get free key →</a>
            )}
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Paste your API key"
            className="w-full border rounded px-3 py-1.5 text-sm"
          />
          <p className="text-[11px] text-gray-500 mt-0.5">
            Stored only in this browser. Sent to this server just to call the provider; never saved or logged server-side.
          </p>
          <button type="button" onClick={() => { clearPrefs(); setApiKey(""); }}
            className="text-[11px] text-gray-400 hover:text-red-500 mt-0.5">
            Saved in this browser · Forget saved keys
          </button>
        </div>
      )}
    </div>
  );
}

function JobProgress({ count, job, active }) {
  if (!active && !job) return null;
  const finished = !active && job?.finished;
  let tone = "text-gray-600", text;
  if (!finished) {
    const phase = job?.phase && job.phase !== "generating" ? `${job.phase}…` : "Generating…";
    text = `${phase} ${count} questions${job?.total_chunks ? ` · chunk ${job.done_chunks}/${job.total_chunks}` : ""}`;
  } else if (job.total_chunks === 0) {
    tone = "text-red-600";
    text = `✗ Failed: ${job.last_error || "no readable text found in the source."}`;
  } else if (job.failed_chunks === job.total_chunks) {
    tone = "text-red-600";
    text = `✗ Failed: no questions generated (${job.failed_chunks}/${job.total_chunks} chunks failed).`;
  } else if (job.failed_chunks > 0) {
    tone = "text-amber-600";
    text = `⚠ Finished with errors: ${count} questions in the label; ${job.failed_chunks}/${job.total_chunks} chunks failed.`;
  } else {
    tone = "text-green-700";
    text = `✓ Done: questions generated from ${job.total_chunks} chunk(s). Label now has ${count} questions.`;
  }
  return (
    <div className={`mt-2 text-sm font-medium ${tone}`}>
      <p className={!finished ? "animate-pulse font-normal text-xs" : ""}>{text}</p>
      {job?.pages_read > 0 && (
        <p className="text-xs font-normal text-gray-600">
          Notion pages read: {job.pages_read}
          {job.pages_skipped > 0 && (
            <span className="text-amber-600"> · {job.pages_skipped} sub-page(s) skipped (page limit reached)</span>
          )}
        </p>
      )}
      {job?.images_found > 0 && (
        <p className="text-xs font-normal text-gray-600">
          Images: {job.images_read} read{job.images_failed > 0 ? `, ${job.images_failed} failed/skipped` : ""} of {job.images_found}
        </p>
      )}
      {job?.image_errors?.length > 0 && job.total_chunks > 0 && (
        <p className="text-xs font-normal text-amber-600">Image error: {job.image_errors[0]}</p>
      )}
      {job?.last_error && finished && job.total_chunks > 0 && (
        <p className="text-xs font-normal text-red-600">Last error: {job.last_error}</p>
      )}
      {job?.last_error && !finished && (
        <p className="text-xs font-normal text-red-600">Last error: {job.last_error}</p>
      )}
    </div>
  );
}

export default function QuestionBank() {
  const isDemo = localStorage.getItem("username") === "demo";
  const [labels, setLabels] = useState([]);
  const [providers, setProviders] = useState({});
  const [selectedLabel, setSelectedLabel] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [activeTab, setActiveTab] = useState("upload");

  // Upload form
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState("");
  const [polling, setPolling] = useState(null);
  const [pollCount, setPollCount] = useState(null);
  const [pollJob, setPollJob] = useState(null);
  const { provider: upProvider, setProvider: setUpProvider, model: upModel, setModel: setUpModel, apiKey: upApiKey, setApiKey: setUpApiKey } = useLLMPrefs();
  const [upMax, setUpMax] = useState("");
  const fileRef = useRef();
  const labelRef = useRef();

  // Notion form
  const [notionLabel, setNotionLabel] = useState("");
  const [notionUrl, setNotionUrl] = useState("");
  const notionTokenKey = `examprep:notion:${localStorage.getItem("username") || "anon"}`;
  const [notionToken, setNotionToken] = useState(() => {
    try { return localStorage.getItem(notionTokenKey) || ""; } catch { return ""; }
  });
  useEffect(() => {
    try { notionToken ? localStorage.setItem(notionTokenKey, notionToken) : localStorage.removeItem(notionTokenKey); } catch { /* ignore */ }
  }, [notionToken]);
  const { provider: notionProvider, setProvider: setNotionProvider, model: notionModel, setModel: setNotionModel, apiKey: notionApiKey, setApiKey: setNotionApiKey } = useLLMPrefs();
  const [notionMax, setNotionMax] = useState("");
  const [notionReadImages, setNotionReadImages] = useState(false);
  const [notionLoading, setNotionLoading] = useState(false);
  const [notionMsg, setNotionMsg] = useState("");
  const [notionPolling, setNotionPolling] = useState(null);
  const [notionPollCount, setNotionPollCount] = useState(null);
  const [notionJob, setNotionJob] = useState(null);

  // Topic form
  const [topicLabel, setTopicLabel] = useState("");
  const [topic, setTopic] = useState("");
  const [topicN, setTopicN] = useState(3);
  const { provider: topicProvider, setProvider: setTopicProvider, model: topicModel, setModel: setTopicModel, apiKey: topicApiKey, setApiKey: setTopicApiKey } = useLLMPrefs();
  const [topicLoading, setTopicLoading] = useState(false);
  const [topicMsg, setTopicMsg] = useState("");

  const PAGE_SIZE = 15;
  const loadLabels = () => getLabels().then(setLabels);

  useEffect(() => {
    loadLabels();
    getProviders().then(setProviders).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedLabel) return;
    getQuestions(selectedLabel.id, page, PAGE_SIZE).then((r) => {
      setQuestions(r.items);
      setTotal(r.total);
    });
  }, [selectedLabel, page]);

  // Poll after upload
  useEffect(() => {
    if (!polling) return;
    const id = setInterval(async () => {
      const { question_count, job } = await getLabelStatus(polling);
      setPollCount(question_count);
      setPollJob(job);
      if (job?.finished) { setPolling(null); setUploadMsg(""); loadLabels(); }
    }, 3000);
    return () => clearInterval(id);
  }, [polling]);

  // Poll after Notion ingest
  useEffect(() => {
    if (!notionPolling) return;
    const id = setInterval(async () => {
      const { question_count, job } = await getLabelStatus(notionPolling);
      setNotionPollCount(question_count);
      setNotionJob(job);
      if (job?.finished) { setNotionPolling(null); setNotionMsg(""); loadLabels(); }
    }, 3000);
    return () => clearInterval(id);
  }, [notionPolling]);

  const handleNotionIngest = async (e) => {
    e.preventDefault();
    setNotionMsg("");
    if (!notionLabel.trim() || !notionUrl.trim() || !notionToken.trim()) return;
    setNotionLoading(true);
    try {
      const r = await fromNotion({
        label: notionLabel.trim(),
        page_url: notionUrl.trim(),
        notion_api_key: notionToken.trim(),
        provider: notionProvider,
        model: notionModel.trim(),
        api_key: notionApiKey.trim(),
        max_questions: notionMax ? Number(notionMax) : null,
        read_images: notionProvider === "gemini" && notionReadImages,
      });
      setNotionMsg(`✓ "${r.page_title}" accepted. Fetching pages${r.read_images ? ", reading images" : ""} and generating in the background…`);
      setNotionPolling(notionLabel.trim());
      setNotionPollCount(0);
    } catch (err) {
      setNotionMsg(`Error: ${err.message}`);
    } finally {
      setNotionLoading(false);
    }
  };

  const handleTopicGenerate = async (e) => {
    e.preventDefault();
    setTopicMsg("");
    if (!topicLabel.trim() || !topic.trim()) return;
    setTopicLoading(true);
    try {
      const r = await generateFromTopic({
        label: topicLabel.trim(),
        topic: topic.trim(),
        num_questions: topicN,
        provider: topicProvider,
        model: topicModel.trim(),
        api_key: topicApiKey.trim(),
      });
      setTopicMsg(`✓ ${r.generated} questions added to "${r.label}" via ${r.provider}.`);
      loadLabels();
    } catch (err) {
      setTopicMsg(`Error: ${err.message}`);
    } finally {
      setTopicLoading(false);
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    const file = fileRef.current.files[0];
    const label = labelRef.current.value.trim();
    if (!file || !label) return;

    const fd = new FormData();
    fd.append("file", file);
    fd.append("label", label);
    fd.append("provider", upProvider);
    fd.append("model", upModel.trim());
    fd.append("api_key", upApiKey.trim());
    if (upMax) fd.append("max_questions", upMax);

    setUploading(true);
    setUploadMsg("");
    try {
      const r = await uploadFile(fd);
      setUploadMsg(r.message);
      setPolling(label);
      setPollCount(0);
      fileRef.current.value = "";
    } catch (err) {
      setUploadMsg(`Error: ${err.message}`);
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteQ = async (id) => {
    await deleteQuestion(id);
    setQuestions((qs) => qs.filter((q) => q.id !== id));
    setTotal((t) => t - 1);
    loadLabels();
  };

  const handleDeleteLabel = async (label) => {
    if (!confirm(`Delete label "${label.name}" and all its questions?`)) return;
    await deleteLabel(label.id);
    setLabels((ls) => ls.filter((l) => l.id !== label.id));
    if (selectedLabel?.id === label.id) { setSelectedLabel(null); setQuestions([]); }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Question Bank</h1>

      {/* Add questions — tabbed */}
      {isDemo ? (
        <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-4 mb-8 text-sm text-indigo-900">
          You're using the shared demo account: browse the sample CIPP/E questions and take an exam from
          <b> New Exam</b>. Uploading, generating and deleting are disabled. Sign up for a free account to
          generate questions from your own PDFs, Word files, text notes or Notion pages.
        </div>
      ) : (
      <div className="bg-white rounded-xl border border-gray-200 mb-8 overflow-hidden">
        <div className="flex border-b border-gray-200">
          {[
            { key: "upload", label: "📄 Upload Document" },
            { key: "topic",  label: "✨ Generate from Topic" },
            { key: "notion", label: "📓 From Notion" },
          ].map(({ key, label }) => (
              <button key={key} onClick={() => { setActiveTab(key); setUploadMsg(""); setTopicMsg(""); setNotionMsg(""); }}
                className={`px-5 py-3 text-sm font-medium transition ${
                  activeTab === key ? "border-b-2 border-indigo-600 text-indigo-700" : "text-gray-500 hover:text-gray-700"
                }`}>{label}</button>
            ))}
        </div>

        <div className="p-5">
          {/* Upload tab */}
          {activeTab === "upload" && (
            <>
              <form onSubmit={handleUpload} className="space-y-3">
                <div className="flex flex-wrap gap-3 items-end">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">File (PDF, DOCX, or TXT)</label>
                    <input ref={fileRef} type="file" accept=".pdf,.docx,.txt" required
                      className="text-sm border rounded px-2 py-1" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Label</label>
                    <input ref={labelRef} type="text" placeholder="e.g. CISSP Domain 1" required
                      className="border rounded px-3 py-1.5 text-sm w-48" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Max questions (optional)</label>
                    <input type="number" min={1} max={500} value={upMax} onChange={(e) => setUpMax(e.target.value)}
                      placeholder="auto"
                      className="w-32 border rounded px-3 py-1.5 text-sm" />
                  </div>
                </div>
                <ProviderFields
                  provider={upProvider} setProvider={setUpProvider}
                  model={upModel} setModel={setUpModel}
                  apiKey={upApiKey} setApiKey={setUpApiKey}
                  providers={providers}
                />
                <button type="submit" disabled={uploading}
                  className="bg-indigo-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
                  {uploading ? "Uploading…" : "Upload & Generate"}
                </button>
              </form>
              {uploadMsg && <p className="mt-2 text-sm text-indigo-700">{uploadMsg}</p>}
              <JobProgress count={pollCount} job={pollJob} active={!!polling} />
            </>
          )}

          {/* Topic tab */}
          {activeTab === "topic" && (
            <>
              <p className="text-xs text-gray-500 mb-3">
                Generate questions from model knowledge — no document needed.
                {topicProvider === "ollama" && (
                  <span className="ml-1 text-amber-600">Ollama on CPU is slow; keep questions ≤ 5.</span>
                )}
              </p>
              <form onSubmit={handleTopicGenerate} className="space-y-3">
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="flex-1 min-w-48">
                    <label className="block text-xs text-gray-500 mb-1">Label</label>
                    <input type="text" value={topicLabel} onChange={(e) => setTopicLabel(e.target.value)}
                      placeholder="e.g. CISSP Domain 3" required
                      className="w-full border rounded px-3 py-1.5 text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Number of questions</label>
                    <input type="number" min={1} max={100} value={topicN}
                      onChange={(e) => setTopicN(Number(e.target.value))}
                      className="w-24 border rounded px-3 py-1.5 text-sm" />
                  </div>
                </div>
                <ProviderFields
                  provider={topicProvider} setProvider={setTopicProvider}
                  model={topicModel} setModel={setTopicModel}
                  apiKey={topicApiKey} setApiKey={setTopicApiKey}
                  providers={providers}
                />
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Topic description</label>
                  <textarea value={topic} onChange={(e) => setTopic(e.target.value)} required rows={3}
                    placeholder="e.g. CISSP Domain 3: Security Architecture — cryptography, PKI, and key management"
                    className="w-full border rounded px-3 py-2 text-sm resize-none" />
                </div>
                <button type="submit" disabled={topicLoading}
                  className="bg-indigo-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
                  {topicLoading ? "Generating… (please wait)" : "Generate Questions"}
                </button>
              </form>
              {topicMsg && (
                <p className={`mt-2 text-sm ${topicMsg.startsWith("Error") ? "text-red-600" : "text-green-700"}`}>
                  {topicMsg}
                </p>
              )}
            </>
          )}

          {/* Notion tab */}
          {activeTab === "notion" && (
            <>
              <div className="text-xs text-gray-600 bg-indigo-50 border border-indigo-100 rounded-lg p-3 mb-4">
                <p className="font-semibold mb-1">How to set up (one-time):</p>
                <ol className="list-decimal ml-4 space-y-1">
                  <li>
                    <b>Create a Notion integration:</b> open{" "}
                    <a href="https://www.notion.so/my-integrations" target="_blank" rel="noreferrer"
                      className="text-indigo-600 underline">notion.so/my-integrations</a>
                    , click <i>New integration</i>, pick your workspace and save. Copy the{" "}
                    <i>Internal Integration Secret</i> (starts with <code>secret_</code> or <code>ntn_</code>) into the token field below.
                  </li>
                  <li>
                    <b>Share your page with it:</b> open the page in Notion → click <code>…</code> (top right) →{" "}
                    <i>Connections</i> (or <i>Add connections</i>) → select your integration.
                    Without this, import fails with "page not found".
                  </li>
                  <li>
                    <b>Copy the page URL:</b> use <i>Share → Copy link</i> (or the browser address bar) and paste it below.
                  </li>
                </ol>
                <p className="mt-2 text-gray-500">
                  Tip: each paragraph needs 100+ characters to be used; headings split the page into sections.
                </p>
              </div>
              <form onSubmit={handleNotionIngest} className="space-y-3">
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="flex-1 min-w-48">
                    <label className="block text-xs text-gray-500 mb-1">Label</label>
                    <input type="text" value={notionLabel} onChange={(e) => setNotionLabel(e.target.value)}
                      placeholder="e.g. CIPP/E Notes" required
                      className="w-full border rounded px-3 py-1.5 text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Max questions (optional)</label>
                    <input type="number" min={1} max={500} value={notionMax} onChange={(e) => setNotionMax(e.target.value)}
                      placeholder="auto"
                      className="w-32 border rounded px-3 py-1.5 text-sm" />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Notion Page URL</label>
                  <input type="url" value={notionUrl} onChange={(e) => setNotionUrl(e.target.value)}
                    placeholder="https://www.notion.so/Your-Page-Title-abc123..." required
                    className="w-full border rounded px-3 py-1.5 text-sm" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    Notion Integration Token{" "}
                    <a href="https://www.notion.so/my-integrations" target="_blank" rel="noreferrer"
                      className="text-indigo-500 underline">Get token →</a>
                  </label>
                  <input type="password" value={notionToken} onChange={(e) => setNotionToken(e.target.value)}
                    placeholder="secret_..." required
                    className="w-full border rounded px-3 py-1.5 text-sm" />
                </div>
                <ProviderFields
                  provider={notionProvider} setProvider={setNotionProvider}
                  model={notionModel} setModel={setNotionModel}
                  apiKey={notionApiKey} setApiKey={setNotionApiKey}
                  providers={providers}
                />
                {notionProvider === "gemini" ? (
                  <label className="flex items-start gap-2 text-xs text-gray-600">
                    <input type="checkbox" checked={notionReadImages}
                      onChange={(e) => setNotionReadImages(e.target.checked)} className="mt-0.5" />
                    <span>
                      Also read images (diagrams, screenshots) using Gemini vision. Up to 15 images per page;
                      uses extra API calls and is slower.
                    </span>
                  </label>
                ) : (
                  <p className="text-xs text-gray-400">
                    Images in the page are skipped. Choose Gemini to also read images.
                  </p>
                )}
                <button type="submit" disabled={notionLoading}
                  className="bg-indigo-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
                  {notionLoading ? "Fetching page…" : "Import & Generate"}
                </button>
              </form>
              {notionMsg && (
                <p className={`mt-2 text-sm ${notionMsg.startsWith("Error") ? "text-red-600" : "text-indigo-700"}`}>
                  {notionMsg}
                </p>
              )}
              <JobProgress count={notionPollCount} job={notionJob} active={!!notionPolling} />
            </>
          )}
        </div>
      </div>

      )}

      {/* Labels + Questions */}
      <div className="grid grid-cols-3 gap-6">
        <div>
          <h2 className="font-semibold text-sm text-gray-500 uppercase mb-2">Labels</h2>
          {labels.length === 0 && <p className="text-sm text-gray-400">No labels yet.</p>}
          <div className="space-y-1">
            {labels.map((l) => (
              <div key={l.id}
                className={`flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer text-sm ${
                  selectedLabel?.id === l.id ? "bg-indigo-600 text-white" : "hover:bg-gray-100"
                }`}
                onClick={() => { setSelectedLabel(l); setPage(1); }}
              >
                <span className="truncate">{l.name}</span>
                <div className="flex items-center gap-2 ml-2 shrink-0">
                  <span className={`text-xs ${selectedLabel?.id === l.id ? "text-indigo-100" : "text-gray-400"}`}>
                    {l.question_count}
                  </span>
                  {!isDemo && (<button onClick={(e) => { e.stopPropagation(); handleDeleteLabel(l); }}
                    className="text-red-400 hover:text-red-600 text-xs" title="Delete label">✕</button>)}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="col-span-2">
          {!selectedLabel && <p className="text-gray-400 text-sm">Select a label to view questions.</p>}
          {selectedLabel && (
            <>
              <h2 className="font-semibold mb-3">
                {selectedLabel.name} — {total} question{total !== 1 ? "s" : ""}
              </h2>
              <div className="space-y-3">
                {questions.map((q) => (
                  <div key={q.id} className="bg-white border border-gray-200 rounded-lg p-4 text-sm">
                    <div className="flex justify-between">
                      <p className="font-medium flex-1 pr-4">{q.question_text}</p>
                      {!isDemo && (<button onClick={() => handleDeleteQ(q.id)}
                        className="text-red-400 hover:text-red-600 text-xs shrink-0">✕</button>)}
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-1 text-gray-600">
                      {Object.entries(q.options).map(([k, v]) => (
                        <p key={k} className={k === q.answer ? "text-green-700 font-medium" : ""}>
                          {k}) {v}
                        </p>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              {total > PAGE_SIZE && (
                <div className="flex gap-2 mt-4 justify-center">
                  <button disabled={page === 1} onClick={() => setPage((p) => p - 1)}
                    className="px-3 py-1 border rounded text-sm disabled:opacity-40">← Prev</button>
                  <span className="text-sm self-center">Page {page} of {Math.ceil(total / PAGE_SIZE)}</span>
                  <button disabled={page >= Math.ceil(total / PAGE_SIZE)} onClick={() => setPage((p) => p + 1)}
                    className="px-3 py-1 border rounded text-sm disabled:opacity-40">Next →</button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
