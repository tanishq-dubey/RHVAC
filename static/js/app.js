$(document).ready(function(){
    //connect to the socket server.
    var socket = io.connect('http://' + document.domain + ':' + location.port + '/data');
    var numbers_received = [];

    //receive details from server
    socket.on('tempHeartbeat', function(msg) {
        console.log("Received temp" + msg.temp);
        $('#curr_temp').html(numbers_string);
    });

});
