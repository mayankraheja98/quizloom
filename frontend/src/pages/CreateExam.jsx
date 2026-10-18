import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getLabels, createExam } from "../api/client";

export default function CreateExam() {
  const [labels, setLabels] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [numQ, setNumQ] = useState(20);
  const [timerMin, setTimerMin] = useState(45);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    getLabels().then(setLabels);
  }, []);

  const toggleLabel = (id) => {
    setSelectedIds((ids) =>
      ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id]
    );
  };

  const availableQ = labels
    .filter((l) => selectedIds.includes(l.id))
    .reduce((sum, l) => sum + l.question_count, 0);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (selectedIds.length === 0) return setError("Select at least one label.");
    if (numQ < 1) return setError("Number of questions must be at least 1.");
    if (numQ > availableQ) return setError(`Only ${availableQ} questions available.`);

    setLoading(true);
    try {
      const { session_id } = await createExam({
        name,
        label_ids: selectedIds,
        num_questions: numQ,
        timer_seconds: timerMin * 60,
      });
      navigate(`/exam/${session_id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-xl">
      <h1 className="text-2xl font-bold mb-6">Create Exam</h1>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Labels */}
        <div>
          <label className="block text-sm font-medium mb-2">
            Question Bank Labels
          </label>
          {labels.length === 0 && (
            <p className="text-sm text-gray-400">
              No labels found. Upload documents in Question Bank first.
            </p>
          )}
          <div className="space-y-2">
            {labels.map((l) => (
              <label
                key={l.id}
                className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition ${
                  selectedIds.includes(l.id)
                    ? "border-indigo-500 bg-indigo-50"
                    : "border-gray-200 hover:border-gray-300"
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedIds.includes(l.id)}
                  onChange={() => toggleLabel(l.id)}
                  className="accent-indigo-600"
                />
                <span className="flex-1 text-sm font-medium">{l.name}</span>
                <span className="text-xs text-gray-400">
                  {l.question_count} questions
                </span>
              </label>
            ))}
          </div>
          {availableQ > 0 && (
            <p className="text-xs text-gray-500 mt-1">
              {availableQ} questions available from selected labels
            </p>
          )}
        </div>

        {/* Exam name */}
        <div>
          <label className="block text-sm font-medium mb-1">Exam Name (optional)</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. CISSP Practice Test #1"
            className="w-full border rounded-lg px-3 py-2 text-sm"
          />
        </div>

        {/* Number of questions */}
        <div>
          <label className="block text-sm font-medium mb-1">
            Number of Questions
          </label>
          <input
            type="number"
            min={1}
            max={availableQ || 500}
            value={numQ}
            onChange={(e) => setNumQ(Number(e.target.value))}
            className="w-32 border rounded-lg px-3 py-2 text-sm"
          />
        </div>

        {/* Timer */}
        <div>
          <label className="block text-sm font-medium mb-1">Timer (minutes)</label>
          <input
            type="number"
            min={1}
            max={360}
            value={timerMin}
            onChange={(e) => setTimerMin(Number(e.target.value))}
            className="w-32 border rounded-lg px-3 py-2 text-sm"
          />
          <p className="text-xs text-gray-400 mt-1">
            ~{Math.round((timerMin * 60) / numQ)} seconds per question
          </p>
        </div>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        <button
          type="submit"
          disabled={loading || labels.length === 0}
          className="w-full bg-indigo-600 text-white py-2.5 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? "Creating…" : "Start Exam"}
        </button>
      </form>
    </div>
  );
}
