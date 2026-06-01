const imageUpload = document.getElementById('imageUpload');
const textInput = document.getElementById('textInput');
const downloadBtn = document.getElementById('downloadBtn');
const canvas = document.getElementById('canvas');

const baseImage = new Image();
baseImage.src = "img/idcard.png";
let overlayImage = null;


baseImage.onload = () => {
    drawCanvas();
};


imageUpload.addEventListener('change', (event) => {
    const file = event.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(e) {
            overlayImage = new Image();
            overlayImage.src = e.target.result;
            overlayImage.onload = drawCanvas; 
        };
        reader.readAsDataURL(file);
    }
});

// Mettre à jour le texte en temps réel
textInput.addEventListener('input', drawCanvas);

downloadBtn.addEventListener('click', () => {
    const link = document.createElement('a');
    link.download = 'USUG_IDcard.png';
    link.href = canvas.toDataURL();
    link.click();
});

function drawCanvas() {
    const ctx = canvas.getContext('2d');
    const scaleFactor = 0.5; // Reduction factor

    canvas.width = baseImage.width * scaleFactor;
    canvas.height = baseImage.height * scaleFactor;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(baseImage, 0, 0, canvas.width, canvas.height);

    if (overlayImage) {
        const imageX = canvas.width * 0.94 - 258 * scaleFactor;
        const imageY = canvas.height * 0.095;
        ctx.drawImage(overlayImage, imageX, imageY, 258 * scaleFactor, 350 * scaleFactor);
    }

    ctx.font = `${3 * scaleFactor}rem Arial`;
    ctx.fillStyle = 'black';

    const text = textInput.value.toUpperCase();
    const textX = canvas.width * 0.05;
    const textY = canvas.height * 0.9;

    ctx.fillText(text, textX, textY);
}






