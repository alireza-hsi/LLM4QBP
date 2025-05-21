import { layoutProcess } from './dist/index.js';
import fs from 'fs/promises';
import path from 'path';

async function main() {
    const inputPath = process.argv[2];

    if (!inputPath) {
        console.error('Please provide a path to your BPMN file');
        console.error('Usage: node layout.js <path-to-bpmn-file>');
        process.exit(1);
    }

    try {
        // Read input BPMN file
        const inputBpmn = await fs.readFile(inputPath, 'utf-8');

        // Layout the process
        const layoutedBpmn = await layoutProcess(inputBpmn);

        // Save to same directory as input file
        const outputPath = path.join(path.dirname(inputPath), 'output-diagram.bpmn');
        await fs.writeFile(outputPath, layoutedBpmn);
        console.log(`Layout complete! Saved to: ${outputPath}`);
    } catch (error) {
        console.error('Error:', error);
        process.exit(1);
    }
}

main();