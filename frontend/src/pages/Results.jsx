import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getResults } from "../api/client";

const OPTION_LABELS = { A: "A", B: "B", C: "C", D: "D" };

export default function Results() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [results, setResults] = useState(null);
  const [filter, setFilter] = useState("all"); // all | correct | incorrect

  useEffect(() => {
    getResults(Number(id)).then(setResults);
  }, [id]);

  if (!results) return <p className="text-gray-400">Loading results…</p>;

  const { score, total, percentage, items, name } = results;
  const passing = percentage >= 70;

  const filtered = items.filter((item) => {
    if (filter === "correct") return item.is_correct;
    if (filter === "incorrect") return !item.is_correct;
    return true;
  });

  return (
    <div className="max-w-2xl mx-auto">
      {/* Score summary */}
      <div
        className={`rounded-xl p-6 mb-8 text-center ${
          passing ? "bg-green-50 border border-green-200" : "bg-red-50 border border-red-200"
        }`}
      >
        <p className="text-sm font-medium text-gray-500 mb-1">{name}</p>
        <p
          className={`text-6xl font-bold mb-2 ${
            passing ? "text-green-600" : "text-red-500"
          }`}
        >
          {percentage}%
        </p>
        <p className="text-gray-600">
          {score} correct out of {total} questions
        </p>
        <p className={`text-sm font-semibold mt-2 ${passing ? "text-green-700" : "text-red-600"}`}>
          {passing ? "✓ Pass" : "✗ Needs improvement"}
        </p>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 mb-5">
        {[
          { key: "all", label: `All (${total})` },
          { key: "correct", label: `Correct (${items.filter((i) => i.is_correct).length})` },
          { key: "incorrect", label: `Incorrect (${items.filter((i) => !i.is_correct).length})` },
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
              filter === key
                ? "bg-indigo-600 text-white"
                : "bg-white border border-gray-200 text-gray-600 hover:border-gray-400"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Question review */}
      <div className="space-y-4">
        {filtered.map((item, idx) => (
          <div
            key={item.question_id}
            className={`bg-white rounded-xl border p-5 ${
              item.is_correct ? "border-green-200" : "border-red-200"
            }`}
          >
            <div className="flex items-start gap-3">
              <span
                className={`mt-0.5 text-sm font-bold w-5 shrink-0 ${
                  item.is_correct ? "text-green-600" : "text-red-500"
                }`}
              >
                {item.is_correct ? "✓" : "✗"}
              </span>
              <div className="flex-1">
                <p className="font-medium text-sm mb-3">{item.question_text}</p>

                <div className="space-y-1.5">
                  {Object.entries(item.options).map(([key, text]) => {
                    const isCorrect = key === item.correct_answer;
                    const isUser = key === item.user_answer;
                    let cls = "text-gray-600";
                    if (isCorrect) cls = "text-green-700 font-semibold";
                    if (isUser && !isCorrect) cls = "text-red-600 line-through";

                    return (
                      <p key={key} className={`text-sm ${cls}`}>
                        <span className="font-medium">{key}.</span> {text}
                        {isCorrect && " ✓"}
                        {isUser && !isCorrect && " (your answer)"}
                      </p>
                    );
                  })}
                </div>

                {item.user_answer === null && (
                  <p className="text-xs text-gray-400 mt-2">Skipped / timed out</p>
                )}

                {item.explanation && (
                  <div className="mt-3 text-xs text-gray-600 bg-gray-50 rounded p-3 border border-gray-100">
                    <span className="font-semibold">Explanation: </span>
                    {item.explanation}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-3 mt-8">
        <button
          onClick={() => navigate("/create")}
          className="flex-1 bg-indigo-600 text-white py-2.5 rounded-lg font-medium hover:bg-indigo-700 text-sm"
        >
          Take Another Exam
        </button>
        <button
          onClick={() => navigate("/")}
          className="flex-1 border border-gray-300 py-2.5 rounded-lg font-medium hover:bg-gray-50 text-sm"
        >
          Dashboard
        </button>
      </div>
    </div>
  );
}
