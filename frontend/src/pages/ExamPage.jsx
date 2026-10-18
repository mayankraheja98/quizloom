import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getExam, startExam, submitExam } from "../api/client";
import Timer from "../components/Timer";

export default function ExamPage() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [exam, setExam] = useState(null);
  const [current, setCurrent] = useState(0);          // question index
  const [answers, setAnswers] = useState({});          // { questionId: "A"|"B"|... }
  const [selected, setSelected] = useState(null);      // current question selection
  const [submitting, setSubmitting] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const submittedRef = useRef(false);

  useEffect(() => {
    getExam(Number(id)).then((data) => {
      setExam(data);
      startExam(Number(id));
    });
  }, [id]);

  const doSubmit = useCallback(
    async (finalAnswers) => {
      if (submittedRef.current) return;
      submittedRef.current = true;
      setSubmitting(true);

      const payload = exam.questions.map((q) => ({
        question_id: q.id,
        user_answer: finalAnswers[q.id] ?? null,
      }));

      await submitExam(Number(id), payload);
      navigate(`/results/${id}`);
    },
    [exam, id, navigate]
  );

  const handleTimerExpire = useCallback(() => {
    setTimedOut(true);
    // Merge current pending selection into answers before submitting
    setAnswers((prev) => {
      const merged = { ...prev };
      const currentQ = exam?.questions[current];
      if (currentQ && selected) merged[currentQ.id] = selected;
      doSubmit(merged);
      return merged;
    });
  }, [exam, current, selected, doSubmit]);

  if (!exam) return <p className="text-gray-400">Loading exam…</p>;

  const q = exam.questions[current];
  const isLast = current === exam.questions.length - 1;

  const handleNext = () => {
    // Persist selection
    const newAnswers = selected ? { ...answers, [q.id]: selected } : answers;
    setAnswers(newAnswers);
    setSelected(null);

    if (isLast) {
      doSubmit(newAnswers);
    } else {
      setCurrent((c) => c + 1);
    }
  };

  const handleSkip = () => {
    setSelected(null);
    if (isLast) {
      doSubmit(answers);
    } else {
      setCurrent((c) => c + 1);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-bold text-lg">{exam.name}</h1>
          <p className="text-sm text-gray-500">
            Question {current + 1} of {exam.total}
          </p>
        </div>
        <Timer totalSeconds={exam.timer_seconds} onExpire={handleTimerExpire} />
      </div>

      {/* Progress bar */}
      <div className="w-full bg-gray-200 rounded-full h-1.5 mb-8">
        <div
          className="bg-indigo-500 h-1.5 rounded-full transition-all"
          style={{ width: `${((current) / exam.total) * 100}%` }}
        />
      </div>

      {/* Question card */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
        <p className="text-base font-medium mb-5">{q.question_text}</p>

        <div className="space-y-3">
          {Object.entries(q.options).map(([key, text]) => (
            <button
              key={key}
              onClick={() => setSelected(key)}
              className={`w-full text-left px-4 py-3 rounded-lg border text-sm transition ${
                selected === key
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
      <div className="flex justify-between mt-6">
        <button
          onClick={handleSkip}
          disabled={submitting || timedOut}
          className="text-sm text-gray-500 hover:text-gray-700 disabled:opacity-40"
        >
          Skip →
        </button>
        <button
          onClick={handleNext}
          disabled={!selected || submitting || timedOut}
          className="bg-indigo-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40"
        >
          {submitting ? "Submitting…" : isLast ? "Submit Exam" : "Next →"}
        </button>
      </div>

      {timedOut && (
        <p className="text-center text-red-600 text-sm mt-4 font-medium">
          Time's up! Submitting your answers…
        </p>
      )}
    </div>
  );
}
