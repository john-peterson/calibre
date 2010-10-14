
// Cookies {{{

function cookie(name, value, options) {
    if (typeof value != 'undefined') { // name and value given, set cookie
        options = options || {};
        if (value === null) {
            value = '';
            options.expires = -1;
        }
        var expires = '';
        if (options.expires && (typeof options.expires == 'number' || options.expires.toUTCString)) {
            var date;
            if (typeof options.expires == 'number') {
                date = new Date();
                date.setTime(date.getTime() + (options.expires * 24 * 60 * 60 * 1000));
            } else {
                date = options.expires;
            }
            expires = '; expires=' + date.toUTCString(); // use expires attribute, max-age is not supported by IE
        }
        // CAUTION: Needed to parenthesize options.path and options.domain
        // in the following expressions, otherwise they evaluate to undefined
        // in the packed version for some reason...
        var path = options.path ? '; path=' + (options.path) : '';
        var domain = options.domain ? '; domain=' + (options.domain) : '';
        var secure = options.secure ? '; secure' : '';
        document.cookie = [name, '=', encodeURIComponent(value), expires, path, domain, secure].join('');
    } else { // only name given, get cookie
        var cookieValue = null;
        if (document.cookie && document.cookie != '') {
            var cookies = document.cookie.split(';');
            for (var i = 0; i < cookies.length; i++) {
                var cookie = jQuery.trim(cookies[i]);
                // Does this cookie string begin with the name we want?
                if (cookie.substring(0, name.length + 1) == (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
};

// }}}

// Sort {{{

function init_sort_combobox() {
    $("#sort_combobox").multiselect({
       multiple: false,
       header: sort_select_label,
       noneSelectedText: sort_select_label,
       selectedList: 1,
       click: function(event, ui){
            $(this).multiselect("close");
            cookie(sort_cookie_name, ui.value, {expires: 365});
            window.location.reload();
       }
    });
}

// }}}

function init() {
    $("#container").corner("30px");
    $("#header").corner("30px");
    $("#calibre-home-link").click(function() { window.location = "http://calibre-ebook.com"; });

    init_sort_combobox();

    $("#search_box input:submit").button();
}

// Top-level feed {{{
function toplevel() {
    $(".sort_select").hide();

    $(".toplevel li").corner("15px");

    $(".toplevel li").click(function() {
        var href = $(this).children("span").html();
        window.location = href;
    });
}
// }}}

function render_error(msg) {
    return '<div class="ui-widget"><div class="ui-state-error ui-corner-all" style="padding: 0pt 0.7em"><p><span class="ui-icon ui-icon-alert" style="float: left; margin-right: 0.3em">&nbsp;</span><strong>Error: </strong>'+msg+"</p></div></div>"
}

// Category feed {{{
function category() {
    $(".category li").corner("15px");

    $(".category li").click(function() {
        var href = $(this).children("span.href").html();
        window.location = href;
    });

    $(".category a.navlink").button();
    
    $("#groups").accordion({
        collapsible: true,
        active: false,
        autoHeight: false,
        clearStyle: true,
        header: "h3",

        change: function(event, ui) {
            if (ui.newContent) {
                var href = ui.newContent.children("span.load_href").html();
                ui.newContent.children(".loading").show();
                if (href) {
                    $.ajax({
                        url:href,
                        success: function(data) {
                            this.children(".loaded").html(data);
                            this.children(".loaded").show();
                            this.children(".loading").hide();
                        },
                        context: ui.newContent,
                        dataType: "json",
                        timeout: 600000, //milliseconds (10 minutes)
                        error: function(xhr, stat, err) {
                            this.children(".loaded").html(render_error(stat));
                            this.children(".loaded").show();
                            this.children(".loading").hide();
                        }
                    });
                }
            }
        }
    });
}
// }}}


