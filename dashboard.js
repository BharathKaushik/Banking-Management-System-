document.addEventListener("DOMContentLoaded", function () {

    const ctx = document.getElementById("balanceChart");
    if (!ctx) return;

    new Chart(ctx, {
        type: "line",
        data: {
            labels: chartLabels,
            datasets: [{
                label: "Balance",
                data: chartData,
                borderColor: "#4CAF50",
                backgroundColor: "rgba(76,175,80,0.2)",
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
        }
    });

});
