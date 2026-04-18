const StatCard = ({ title, value, unit, color }) => {
  return (
    <div className={`rounded-xl p-5 border border-gray-700 bg-gray-900 shadow-md`}>
      <p className="text-gray-400 text-sm mb-1">{title}</p>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
      <p className="text-gray-500 text-xs mt-1">{unit}</p>
    </div>
  );
};

export default StatCard;