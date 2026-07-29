type Props = {
    title: string;
    value: string;
    subtitle?: string;
    color?: string;
  };
  
  const StatCard = ({ title, value, subtitle, color }: Props) => {
    return (
      <div className="relative group">
  
        {/* glow effect */}
        <div className="absolute inset-0 bg-purple-600/10 blur-xl opacity-0 group-hover:opacity-100 transition"></div>
  
        <div className="relative backdrop-blur-glass bg-card border border-border rounded-2xl p-5 hover:shadow-glow">
  
          <p className="text-xs text-gray-400 mb-2">{title}</p>
  
          <h2 className="text-2xl font-semibold mb-1">{value}</h2>
  
          {subtitle && (
            <p className={`text-xs ${color}`}>
              {subtitle}
            </p>
          )}
        </div>
      </div>
    );
  };
  
  export default StatCard;