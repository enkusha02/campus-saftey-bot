module.exports = async (req, res) => {
  if (req.method === 'POST') {
    const { message } = req.body;

    if (message) {
      const chatId = message.chat.id;
      const text = "Hello! Your campus safety bot is active.";

      // Send a response back to Telegram
      await fetch(`https://api.telegram.org/bot${process.env.BOT_TOKEN}/sendMessage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: chatId, text: text }),
      });
    }
    res.status(200).send('OK');
  } else {
    res.status(200).send('Bot is running!');
  }
};
