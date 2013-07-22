<!DOCTYPE html>
<html lang="en" class="en">
    <head>
        <title>Telemundo Sitemap</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link href="css/bootstrap.min.css" rel="stylesheet">
        <link href="css/bootstrap-responsive.min.css" rel="stylesheet">
        <link href="css/jquery.fancybox.css" rel="stylesheet">
        <link href="css/default.css" rel="stylesheet">
        <!--[if lt IE 9]>
          <script src="http://html5shim.googlecode.com/svn/trunk/html5.js"></script>
        <![endif]-->
    </head>
    <body>
        <div class="wrapper">
<?php
$input_file = __DIR__ . '/assets/sitemap.json';
if (file_exists($input_file)) {
  $records = json_decode(file_get_contents($input_file));
  $columns = array();
  foreach ($records as $record) {
    if (!isset($columns[$record->section])) {
      $columns[$record->section] = array();
    }
    $columns[$record->section][] = $record;
  }
  foreach ($columns as $section => $sites) {
    echo <<<EOF
            <div class="column $section">

EOF;
    foreach ($sites as $site) {
      $class_ar = array('site');
      if ($site->redir) $class_ar[] = 'redirect';
      if ($site->error) $class_ar[] = 'error'.$site->error;
      $classes = join(' ', $class_ar);
      $imgbase = stristr($site->images, 'http://') ? '' : 'assets/';
      echo <<<EOF
                <div class="span2 $classes">
                    <div class="screenshot">
                        <a href="$imgbase$site->images/crop.png" class="link">
                            <img src="$imgbase$site->images/thumb.png" class="image" title="$site->name" />
                        </a>
                    </div>
                    <p class="description" title="$site->name"><a href="$site->destination" target="_blank">$site->name</a></p>
                    <p class="stats" title="$site->url">$site->url</p>
                </div>

EOF;
    }
    echo <<<EOF
            </div>

EOF;
  }
}
?>
        </div>
    </div>
    <script src="js/jquery-1.8.1.min.js"></script>
    <script src="js/jquery.masonry.min.js"></script>
    <script src="js/jquery.fancybox.js"></script>
    <script src="js/bootstrap.min.js"></script>
    <script>
        (function($) {
            $(document).ready(function($) {
                var container = $('.container');
                container.imagesLoaded(function() {
                    // apply masonry layout
                    container.masonry({
                        'itemSelector': '.site'
                    });
                    // reload masonry layout on window resize
                    $(window).bind('resize', function() {
                        container.masonry('reload');
                    });
                    // create lightbox effect
                    $('.link').fancybox({
                        'openEffect': 'fade',
                    	  'closeEffect': 'fade',
                    });
                });
            });
        })(jQuery);
    </script>
</body>
</html>
