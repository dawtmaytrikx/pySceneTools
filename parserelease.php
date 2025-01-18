<?php
require_once __DIR__ . '/scene-release-parser-php/ReleaseParser.php';

use ReleaseParser\ReleaseParser;

if ($argc > 2) {
    $release_name = $argv[1];
    $section = $argv[2];
    
    $parser = new ReleaseParser($release_name, $section);
    $data = $parser->data;
    
    // Output the data as JSON
    echo json_encode($data);
} else {
    echo json_encode(["error" => "Insufficient arguments provided."]);
}
?>