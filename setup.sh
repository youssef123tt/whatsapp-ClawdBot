#!/bin/bash

# WhatsApp ClawdBot Setup Script

echo "🤖 WhatsApp ClawdBot Setup"
echo "=========================="
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Check Node.js version
echo "Checking Node.js version..."
node_version=$(node --version 2>&1)
echo "Node.js version: $node_version"

echo ""
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

echo ""
echo "Installing Node.js dependencies..."
npm install

echo ""
echo "Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created .env file"
    echo "⚠️  Please edit .env and add your API keys"
else
    echo "ℹ️  .env file already exists"
fi

echo ""
echo "Creating directories..."
mkdir -p session chroma_db data

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your ANTHROPIC_API_KEY"
echo "2. Add your phone number to ADMIN_PHONE_NUMBERS"
echo "3. Run: python3 main.py"
echo "4. Scan the QR code with WhatsApp"
echo ""
echo "For more information, see README.md"
