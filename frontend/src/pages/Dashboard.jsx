import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listExams } from "../api/client";

export default function Dashboard() {
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    listExams()
      .then(setExams)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <button
          onClick={() => navigate("/create")}
          className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700"
        >
          + New Exam
        </button>
      </div>

      {loading && <p className="text-gray-500">Loading...</p>}
      {!loading && exams.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg">No exams yet.</p>
          <p className="text-sm mt-1">
            Upload study material in{" "}
            <a href="/bank" className="text-indigo-600 underline">
              Question Bank
            </a>{" "}
            to get started.
          </p>
        </div>
      )}

      {!loading && exams.length > 0 && (
        <div className="space-y-3">
          {exams.map((e) => (
            <div
              key={e.id}
              className="bg-white rounded-xl border border-gray-200 p-4 flex items-center justify-between cursor-pointer hover:border-indigo-400 transition"
              onClick={() => e.completed_at && navigate(`/results/${e.id}`)}
            >
              <div>
                <p className="font-medium">{e.name}</p>
                <p className="text-sm text-gray-500">
                  {e.completed_at
                    ? new Date(e.completed_at).toLocaleString()
                    : "In progress"}
                </p>
              </div>
              {e.percentage !== null && (
                <div className="text-right">
                  <p
                    className={`text-2xl font-bold ${
                      e.percentage >= 70 ? "text-green-600" : "text-red-500"
                    }`}
                  >
                    {e.percentage}%
                  </p>
                  <p className="text-xs text-gray-400">
                    {e.score}/{e.total}
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
