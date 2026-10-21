import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getExam, startExam, submitExam } from "../api/client";
import Timer from "../components/Timer";

export default function ExamPage() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [exam, setExam] = useState(null);
  const [current, setCurrent] = useState(0);        // question index
  const [answers, setAnswers] = useState({});        // { questionId: "A"|"B"|... }
  const [submitting, setSubmitting] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [error, setError] = useState("");
  const submittedRef = useRef(false);
  const answersRef = useRef({});   // always-current copy for the timer callback
  const examRef = useRef(null);

  useEffect(() => {
    getExam(Number(id)).then((data) => {
      examRef.current = data;
      setExam(data);
      startExam(Number(id));
    });
  }, [id]);

  const doSubmit = useCallback(async () => {
    if (submittedRef.current) return;
    submittedRef.current = true;
    setSubmitting(true);
    setConfirmEnd(false);
    try {
      const payload = examRef.current.questions.map((q) => ({
        question_id: q.id,
        user_answer: answersRef.current[q.id] ?? null,
      }));
      await submitExam(Number(id), payload);
      navigate(`/results/${id}`);
    } catch (e) {
      submittedRef.current = false;   // allow retry
      setSubmitting(false);
      setError(`Could not submit: ${e.message}`);
    }
  }, [id, navigate]);

  // Stable identity so <Timer> doesn't restart its tick on every render
  const handleTimerExpire = useCallback(() => {
    setTimedOut(true);
    doSubmit();
  }, [doSubmit]);

  if (!exam) return <p className="text-gray-400">Loading exam…</p>;

  const q = exam.questions[current];
  const isLast = current === exam.questions.length - 1;
  const answeredCount = Object.keys(answers).length;
  const unanswered = exam.total - answeredCount;
  const locked = submitting || timedOut;

  // Selecting saves immediately; clicking the chosen option again clears it
  const choose = (key) => {
    setAnswers((prev) => {
      const next = { ...prev };
      if (next[q.id] === key) delete next[q.id];
      else next[q.id] = key;
      answersRef.current = next;
      return next;
    });
  };

  return (
    <div className="max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="font-bold text-lg">{exam.name}</h1>
          <p className="text-sm text-gray-500">
            Question {current + 1} of {exam.total} · {answeredCount} answered
          </p>
        </div>
        <Timer totalSeconds={exam.timer_seconds} onExpire={handleTimerExpire} />
      </div>

      {/* Progress bar (answered) */}
      <div className="w-full bg-gray-200 rounded-full h-1.5 mb-4">
        <div
          className="bg-indigo-500 h-1.5 rounded-full transition-all"
          style={{ width: `${(answeredCount / exam.total) * 100}%` }}
        />
      </div>

      {/* Question navigator */}
      <div className="flex flex-wrap gap-1.5 mb-6">
        {exam.questions.map((item, i) => {
          const done = answers[item.id] !== undefined;
          return (
            <button
              key={item.id}
              onClick={() => setCurrent(i)}
              disabled={locked}
              title={done ? "Answered" : "Not answered"}
              className={`w-8 h-8 rounded text-xs font-medium border transition ${
                i === current ? "ring-2 ring-indigo-500 " : ""
              }${
                done
                  ? "bg-indigo-600 text-white border-indigo-600"
                  : "bg-white text-gray-600 border-gray-300 hover:border-gray-500"
              }`}
            >
              {i + 1}
            </button>
          );
        })}
      </div>

      {/* Question card */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
        <p className="text-base font-medium mb-5">{q.question_text}</p>

        <div className="space-y-3">
          {Object.entries(q.options).map(([key, text]) => (
            <button
              key={key}
              onClick={() => choose(key)}
              disabled={locked}
              className={`w-full text-left px-4 py-3 rounded-lg border text-sm transition ${
                answers[q.id] === key
                  ? "border-indigo-500 bg-indigo-50 text-indigo-800 font-medium"
                  : "border-gray-200 hover:border-gray-400"
              }`}
            >
              <span className="font-semibold mr-2">{key}.</span>
              {text}
            </button>
          ))}
        </div>
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between mt-6">
        <button
          onClick={() => setCurrent((c) => c - 1)}
          disabled={current === 0 || locked}
          className="px-4 py-2 rounded-lg text-sm border border-gray-300 text-gray-700 hover:bg-gray-100 disabled:opacity-40"
        >
          ← Previous
        </button>

        <button
          onClick={() => setConfirmEnd(true)}
          disabled={locked}
          className="text-sm text-red-600 hover:text-red-800 underline disabled:opacity-40"
        >
          End exam
        </button>

        {isLast ? (
          <button
            onClick={() => setConfirmEnd(true)}
            disabled={locked}
            className="bg-indigo-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40"
          >
            {submitting ? "Submitting…" : "Finish"}
          </button>
        ) : (
          <button
            onClick={() => setCurrent((c) => c + 1)}
            disabled={locked}
            className="bg-indigo-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40"
          >
            Next →
          </button>
        )}
      </div>

      {error && <p className="text-center text-red-600 text-sm mt-4">{error}</p>}

      {timedOut && (
        <p className="text-center text-red-600 text-sm mt-4 font-medium">
          Time's up! Submitting your answers…
        </p>
      )}

      {/* End-exam confirmation */}
      {confirmEnd && !locked && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-xl shadow-lg p-6 max-w-sm w-full">
            <h2 className="font-semibold text-lg mb-2">End exam and see results?</h2>
            <p className="text-sm text-gray-600 mb-1">
              You answered {answeredCount} of {exam.total} questions.
            </p>
            {unanswered > 0 && (
              <p className="text-sm text-amber-700 mb-1">
                {unanswered} unanswered question{unanswered !== 1 ? "s" : ""} will count as incorrect.
              </p>
            )}
            <p className="text-xs text-gray-500 mb-4">This cannot be undone.</p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setConfirmEnd(false)}
                className="px-4 py-2 rounded-lg text-sm border border-gray-300 hover:bg-gray-100"
              >
                Keep going
              </button>
              <button
                onClick={doSubmit}
                className="px-4 py-2 rounded-lg text-sm bg-red-600 text-white hover:bg-red-700"
              >
                End exam
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
