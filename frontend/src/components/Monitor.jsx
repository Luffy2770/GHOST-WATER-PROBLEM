import { useState, useEffect } from "react";
import axios from "axios";
import Navbar from "../components/Navbar";

const Monitor = () => {
  const [data, setData] = useState([]);
  const [zone, setZone] = useState("All");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchLive = async () => {
    try {
      const res = await axios.get("http://localhost:5000/live");
      setData(res.data);
      setError(null);
    } catch (err) {
      setError("Cannot connect to server. Is Flask running?");
    } finally {
      setLoading(false);
    }
  };

  // Fetch on first load
  useEffect(() => {
    fetchLive();
  }, []);

  // Auto refresh every 10 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      fetchLive();
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  // Filter by zone
  const filtered = zone === "All" ? data : data.filter((row) => row.zone === zone);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <Navbar />

      <div className="p-6">
        {/* Page Title */}
        <h1 className="text-2xl font-bold text-white mb-1">Live Monitor</h1>
        <p className="text-gray-400 text-sm mb-6">Auto-refreshes every 10 seconds</p>

        {/* Zone Filter Buttons */}
        <div className="flex gap-3 mb-6">
          {["All", "Z1", "Z2", "Z3"].map((z) => (
            <button
              key={z}
              onClick={() => setZone(z)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
                zone === z
                  ? "bg-blue-600 text-white"
                  : "bg-gray-800 text-gray-400 hover:bg-gray-700"
              }`}
            >
              {z}
            </button>
          ))}
        </div>

        {/* Loading State */}
        {loading && (
          <p className="text-gray-400 text-center py-10">Loading live data...</p>
        )}

        {/* Error State */}
        {error && (
          <div className="bg-red-900 border border-red-600 text-red-300 px-4 py-3 rounded-lg mb-4">
            {error}
          </div>
        )}

        {/* Table */}
        {!loading && !error && (
          <div className="overflow-x-auto rounded-xl border border-gray-800">
            <table className="w-full text-sm">
              <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
                <tr>
                  <th className="px-4 py-3 text-left">Timestamp</th>
                  <th className="px-4 py-3 text-left">Sensor ID</th>
                  <th className="px-4 py-3 text-left">Zone</th>
                  <th className="px-4 py-3 text-left">Pressure</th>
                  <th className="px-4 py-3 text-left">Expected</th>
                  <th className="px-4 py-3 text-left">Flow (LPM)</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Type</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row, index) => (
                  <tr
                    key={index}
                    className={`border-t border-gray-800 ${
                      row.anomaly === 1
                        ? "bg-red-950 hover:bg-red-900"
                        : "bg-green-950 hover:bg-green-900"
                    }`}
                  >
                    <td className="px-4 py-3 text-gray-300">{row.timestamp}</td>
                    <td className="px-4 py-3 text-gray-300">{row.sensor_id}</td>
                    <td className="px-4 py-3 text-gray-300">{row.zone}</td>
                    <td className="px-4 py-3 text-gray-300">{row.pressure}</td>
                    <td className="px-4 py-3 text-gray-300">{row.expected_pressure}</td>
                    <td className="px-4 py-3 text-gray-300">{row.flow_lpm}</td>
                    <td className="px-4 py-3">
                      {row.anomaly === 1 ? (
                        <span className="bg-red-600 text-white px-2 py-1 rounded text-xs font-bold">
                          ANOMALY
                        </span>
                      ) : (
                        <span className="bg-green-600 text-white px-2 py-1 rounded text-xs font-bold">
                          NORMAL
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-300">{row.nrw_type || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {filtered.length === 0 && (
              <p className="text-center text-gray-500 py-8">No data for this zone</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default Monitor;