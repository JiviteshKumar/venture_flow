import { PieChart, Pie, Cell } from "recharts";

const data = [
  { name: "score", value: 63 },
  { name: "rest", value: 37 },
];

const COLORS = ["#F59E0B", "#1F2937"];

const GaugeChart = () => {
  return (
    <div className="bg-card border border-border rounded-2xl p-5 h-[300px] flex flex-col items-center justify-center">
      
      <h2 className="text-sm text-gray-400 mb-4">Risk Score Overview</h2>

      <PieChart width={200} height={200}>
        <Pie
          data={data}
          startAngle={180}
          endAngle={0}
          innerRadius={60}
          outerRadius={80}
          dataKey="value"
        >
          {data.map((_, index) => (
            <Cell key={index} fill={COLORS[index]} />
          ))}
        </Pie>
      </PieChart>

      <div className="text-2xl font-semibold mt-2">63</div>
      <p className="text-xs text-gray-400">
        Moderate Risk • Investable with conditions
      </p>
    </div>
  );
};

export default GaugeChart;