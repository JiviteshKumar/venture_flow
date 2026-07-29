import {
    LineChart as ReLineChart,
    Line,
    XAxis,
    YAxis,
    Tooltip,
    ResponsiveContainer,
    CartesianGrid,
  } from "recharts";
  
  const data = [
    { month: "Aug", value: 1.2 },
    { month: "Sep", value: 1.4 },
    { month: "Oct", value: 1.6 },
    { month: "Nov", value: 1.9 },
    { month: "Dec", value: 2.1 },
    { month: "Jan", value: 2.4 },
    { month: "Feb", value: 2.6 },
    { month: "Mar", value: 2.8 },
  ];
  
  const LineChartComponent = () => {
    return (
      <div className="bg-card border border-border rounded-2xl p-5 h-[300px]">
        <h2 className="text-sm text-gray-400 mb-4">Monthly ARR Growth</h2>
  
        <ResponsiveContainer width="100%" height="100%">
          <ReLineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
            <XAxis dataKey="month" stroke="#6B7280" />
            <YAxis stroke="#6B7280" />
            <Tooltip />
  
            <Line
              type="monotone"
              dataKey="value"
              stroke="#7C3AED"
              strokeWidth={3}
              dot={false}
            />
          </ReLineChart>
        </ResponsiveContainer>
      </div>
    );
  };
  
  export default LineChartComponent;