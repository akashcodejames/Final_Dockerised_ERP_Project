// Add smooth scrolling to all links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        document.querySelector(this.getAttribute('href')).scrollIntoView({
            behavior: 'smooth'
        });
    });
});

// Auto-hide flash messages after 5 seconds
document.addEventListener("DOMContentLoaded", function () {
    let alerts = document.querySelectorAll(".alert");

    alerts.forEach(alert => {
        // Apply the "show" class to make it slide down
        setTimeout(() => {
            alert.classList.add("show");
        }, 100); // Small delay to trigger the animation

        // Auto-hide flash messages after 5 seconds
        setTimeout(() => {
            alert.classList.add("slide-up"); // Slide up
            setTimeout(() => alert.remove(), 500); // Remove after animation
        }, 5000);
    });
});
