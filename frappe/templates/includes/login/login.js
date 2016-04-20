window.disable_signup = {{ disable_signup and "true" or "false" }};
        window.login = {};
        login.bind_events = function() {
        $(window).on("hashchange", function() {
        login.route();
        });
                $(".form-login").on("submit", function(event) {
        event.preventDefault();
                var args = {};
                args.cmd = "login";
                args.usr = ($("#login_email").val() || "").trim();
                args.pwd = $("#login_password").val();
                args.device = "desktop";
                if (!args.usr || !args.pwd) {
        frappe.msgprint(__("Both login and password required"));
                return false;
        }
        login.call(args);
                return false;
        });
                $(".form-signup").on("submit", function(event) {
        event.preventDefault();
                var args = {};
                args.cmd = "frappe.core.doctype.user.user.sign_up";
                args.email = ($("#signup_email").val() || "").trim();
                args.full_name = ($("#signup_fullname").val() || "").trim();
                if (!args.email || !valid_email(args.email) || !args.full_name) {
        frappe.msgprint(__("Valid email and name required"));
                return false;
        }
        login.call(args);
                return false;
        });
                $(".form-forgot").on("submit", function(event) {
        event.preventDefault();
                var args = {};
                args.cmd = "frappe.core.doctype.user.user.reset_password";
                args.user = ($("#forgot_email").val() || "").trim();
                if (!args.user) {
        frappe.msgprint(__("Valid Login id required."));
                return false;
        }
        login.call(args);
                return false;
        });
        }


login.route = function() {

var route = window.location.hash.slice(1);
        var routeLogin = route.split('/');
        routeLog = routeLogin[0];
        console.log(routeLog);
        if (!routeLog){
routeLog = "login";
        }
login[routeLog]();
}

login.login = function() {
$("form").toggle(false);
        $(".form-login").toggle(true);
}

login.integracion = function(){

var rutaSitio = window.location.hash.slice(1);
        var variables = rutaSitio.split('/');
        console.log(variables);
        var formulario = variables[0];
        console.log(formulario);
        var parametrosUsuario = variables[1];
        
        var varUs = decode64(parametrosUsuario);
        console.log(varUs);
        alert("Ingreso a integracion OK");
        return false;
        var rutaVer = window.location.hash;
        var rutaVer2 = window.location.hash.slice(2);
        console.log(rutaVer);
        console.log(rutaVer2);
        event.preventDefault();
        var args = {};
        args.cmd = "login";
        args.usr = ($("#login_email").val() || "").trim();
        args.pwd = $("#login_password").val();
        args.device = "desktop";
        if (!args.usr || !args.pwd) {
frappe.msgprint(__("Both login and password required"));
        return false;
        }
login.call(args);
        return false;
}

login.forgot = function() {
$("form").toggle(false);
        $(".form-forgot").toggle(true);
}

login.signup = function() {
$("form").toggle(false);
        $(".form-signup").toggle(true);
}


// Login
login.call = function(args) {
frappe.freeze();
        $.ajax({
        type: "POST",
                url: "/",
                data: args,
                dataType: "json",
                statusCode: login.login_handlers
        }).always(function(){
frappe.unfreeze();
        });
}

login.login_handlers = (function() {
var get_error_handler = function(default_message) {
return function(xhr, data) {
if (xhr.responseJSON) {
data = xhr.responseJSON;
        }
var message = data._server_messages
        ? JSON.parse(data._server_messages).join("\n") : default_message;
        frappe.msgprint(message);
        };
        }

var login_handlers = {
200: function(data) {
if (data.message == "Logged In") {
window.location.href = get_url_arg("redirect-to") || "/desk";
        } else if (data.message == "No App") {
if (localStorage) {
var last_visited =
        localStorage.getItem("last_visited")
        || get_url_arg("redirect-to");
        localStorage.removeItem("last_visited");
        }

if (last_visited && last_visited != "/login") {
window.location.href = last_visited;
        } else {
window.location.href = "/me";
        }
} else if (["#signup", "#forgot"].indexOf(window.location.hash) !== - 1) {
frappe.msgprint(data.message);
        }
},
        401: get_error_handler(__("Invalid Login")),
        417: get_error_handler(__("Oops! Something went wrong"))
        };
        return login_handlers;
})();
        frappe.ready(function() {
        login.bind_events();
                if (!window.location.hash) {
        window.location.hash = "#login";
        } else {
        $(window).trigger("hashchange");
        }

        $(".form-signup, .form-forgot").removeClass("hide");
                $(document).trigger('login_rendered');
        });
        var keyStr = "ABCDEFGHIJKLMNOP" +
        "QRSTUVWXYZabcdef" +
        "ghijklmnopqrstuv" +
        "wxyz0123456789+/" +
        "=";
        function encode64(input) {
        input = escape(input);
                var output = "";
                var chr1, chr2, chr3 = "";
                var enc1, enc2, enc3, enc4 = "";
                var i = 0;
                do {
                chr1 = input.charCodeAt(i++);
                        chr2 = input.charCodeAt(i++);
                        chr3 = input.charCodeAt(i++);
                        enc1 = chr1 >> 2;
                        enc2 = ((chr1 & 3) << 4) | (chr2 >> 4);
                        enc3 = ((chr2 & 15) << 2) | (chr3 >> 6);
                        enc4 = chr3 & 63;
                        if (isNaN(chr2)) {
                enc3 = enc4 = 64;
                } else if (isNaN(chr3)) {
                enc4 = 64;
                }

                output = output +
                        keyStr.charAt(enc1) +
                        keyStr.charAt(enc2) +
                        keyStr.charAt(enc3) +
                        keyStr.charAt(enc4);
                        chr1 = chr2 = chr3 = "";
                        enc1 = enc2 = enc3 = enc4 = "";
                } while (i < input.length);
                return output;
        }

function decode64(input) {
var output = "";
        var chr1, chr2, chr3 = "";
        var enc1, enc2, enc3, enc4 = "";
        var i = 0;
        // remove all characters that are not A-Z, a-z, 0-9, +, /, or =
        var base64test = /[^A-Za-z0-9\+\/\=]/g;
        if (base64test.exec(input)) {
alert("There were invalid base64 characters in the input text.\n" +
        "Valid base64 characters are A-Z, a-z, 0-9, '+', '/',and '='\n" +
        "Expect errors in decoding.");
}
input = input.replace(/[^A-Za-z0-9\+\/\=]/g, "");
        do {
        enc1 = keyStr.indexOf(input.charAt(i++));
                enc2 = keyStr.indexOf(input.charAt(i++));
                enc3 = keyStr.indexOf(input.charAt(i++));
                enc4 = keyStr.indexOf(input.charAt(i++));
                chr1 = (enc1 << 2) | (enc2 >> 4);
                chr2 = ((enc2 & 15) << 4) | (enc3 >> 2);
                chr3 = ((enc3 & 3) << 6) | enc4;
                output = output + String.fromCharCode(chr1);
                if (enc3 != 64) {
        output = output + String.fromCharCode(chr2);
        }
        if (enc4 != 64) {
        output = output + String.fromCharCode(chr3);
        }

        chr1 = chr2 = chr3 = "";
                enc1 = enc2 = enc3 = enc4 = "";
        } while (i < input.length);
        return unescape(output);
}